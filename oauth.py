"""Login OAuth 2.0 (Microsoft): fluxo com PKCE pelo navegador, renovação do token e XOAUTH2."""
import base64
import hashlib
import html
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import config

ESPERA_LOGIN = 180  # segundos que o programa espera o usuário concluir o login no navegador

# ID do aplicativo registrado no Microsoft Entra (veja o README). Também pode ser
# informado em opcoes.json, na chave oauth_microsoft_client_id.
CLIENT_ID = ""

PROVEDOR = "microsoft"
URL_AUTORIZAR = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
URL_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
ESCOPO = ("https://outlook.office.com/IMAP.AccessAsUser.All "
          "https://outlook.office.com/SMTP.Send offline_access")
DOMINIOS = ("outlook.com", "hotmail.com", "live.com")

_acessos = {}  # e-mail -> (token de acesso, quando expira); o de renovação fica no keyring
_trava = threading.Lock()


class ErroOAuth(Exception):
    """Falha de autorização que só se resolve entrando de novo (mensagem já em português)."""


def suporta(email):
    dominio = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    return dominio in DOMINIOS


def _client_id():
    cid = config.opcao("oauth_microsoft_client_id", "") or CLIENT_ID
    if not cid:
        raise ErroOAuth(
            "Este programa ainda não tem o identificador do aplicativo Microsoft. "
            "Registre o aplicativo (passo a passo no README) e informe o ID em opcoes.json, "
            "na chave oauth_microsoft_client_id.")
    return cid


def _pedir(campos):
    corpo = urllib.parse.urlencode(campos).encode()
    pedido = urllib.request.Request(URL_TOKEN, corpo, {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code not in (400, 401):
            raise  # erro do servidor: é passageiro, tenta de novo depois
        try:
            dados = json.load(e)
        except ValueError:
            dados = {}
        motivo = (dados.get("error_description") or dados.get("error") or "").splitlines()
        raise ErroOAuth(
            "A Microsoft recusou o login. Entre de novo em Ferramentas, Contas, Editar."
            + (f" Motivo: {motivo[0]}" if motivo else "")) from None


def _guardar_acesso(email, dados):
    _acessos[email] = (dados["access_token"], time.time() + int(dados.get("expires_in", 3600)))


def _pagina(titulo, texto):
    return (f'<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>{html.escape(titulo)}</title>'
            f"<h1>{html.escape(titulo)}</h1><p>{html.escape(texto)}</p></html>").encode()


def autorizar(email, cancelar):
    """Abre o navegador no login da Microsoft e devolve o token de renovação.

    Bloqueia até o usuário concluir; 'cancelar' (threading.Event) interrompe a espera."""
    cid = _client_id()
    verificador = secrets.token_urlsafe(64)
    desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    estado = secrets.token_urlsafe(16)
    recebido = {}

    class Retorno(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
            if "code" not in q and "error" not in q:
                self.send_error(404)
                return
            recebido.update(q)
            if "code" in q:
                corpo = _pagina("Tudo certo", "Login concluído. Pode fechar esta aba e voltar ao Simple Email.")
            else:
                corpo = _pagina("Login não concluído", "Volte ao Simple Email para ver o que aconteceu.")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args):
            pass

    servidor = http.server.HTTPServer(("127.0.0.1", 0), Retorno)
    servidor.timeout = 1
    retorno = f"http://localhost:{servidor.server_address[1]}"  # a Microsoft só aceita "localhost"
    try:
        webbrowser.open(URL_AUTORIZAR + "?" + urllib.parse.urlencode({
            "client_id": cid, "response_type": "code", "redirect_uri": retorno,
            "scope": ESCOPO, "state": estado, "login_hint": email,
            "code_challenge": desafio, "code_challenge_method": "S256",
        }))
        limite = time.time() + ESPERA_LOGIN
        while not recebido and not cancelar.is_set() and time.time() < limite:
            servidor.handle_request()
    finally:
        servidor.server_close()

    if cancelar.is_set():
        raise ErroOAuth("Login cancelado.")
    if not recebido:
        raise ErroOAuth("O tempo para concluir o login no navegador acabou. Tente de novo.")
    if recebido.get("state") != estado:
        raise ErroOAuth("A resposta do navegador não confere com o pedido. Tente de novo.")
    if "code" not in recebido:
        motivo = recebido.get("error_description") or recebido.get("error", "")
        raise ErroOAuth(f"A Microsoft não autorizou o acesso. {motivo}".strip())

    dados = _pedir({"grant_type": "authorization_code", "code": recebido["code"], "redirect_uri": retorno,
                    "client_id": cid, "code_verifier": verificador})
    if not dados.get("refresh_token"):
        raise ErroOAuth("A Microsoft não devolveu a autorização permanente. Tente de novo.")
    with _trava:
        _guardar_acesso(email, dados)
    return dados["refresh_token"]


def token_de_acesso(conta):
    """Token de acesso válido da conta, renovado quando falta pouco para vencer."""
    email = conta["email"]
    with _trava:
        atual = _acessos.get(email)
        if atual and atual[1] - time.time() > 60:
            return atual[0]
        refresh = config.obter_refresh(email)
        if not refresh:
            raise ErroOAuth("Falta entrar de novo nesta conta. Use Ferramentas, Contas, Editar.")
        dados = _pedir({"grant_type": "refresh_token", "refresh_token": refresh,
                        "client_id": _client_id(), "scope": ESCOPO})
        if dados.get("refresh_token") and dados["refresh_token"] != refresh:
            config.salvar_refresh(email, dados["refresh_token"])
        _guardar_acesso(email, dados)
        return dados["access_token"]


def cadeia_xoauth2(email, token):
    return f"user={email}\x01auth=Bearer {token}\x01\x01"


def autenticador(cadeia):
    """Função para imaplib.authenticate e smtplib.auth: manda a cadeia uma vez e, se o servidor
    responder com o erro em JSON, devolve vazio para ele encerrar com a falha."""
    enviada = []

    def f(desafio=None):
        if enviada:
            return ""
        enviada.append(1)
        return cadeia
    return f
