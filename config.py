"""Configuração da conta: dados em JSON, senha no Gerenciador de Credenciais do Windows."""
import json
import os

import keyring

SERVICO = "SimpleEmail"
PASTA = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SimpleEmail")
ARQUIVO = os.path.join(PASTA, "config.json")

# domínio -> (IMAP, porta IMAP, SMTP, porta SMTP)
PROVEDORES = {
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "live.com": ("outlook.office365.com", 993, "smtp.office365.com", 587),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465),
    "yahoo.com.br": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465),
    "uol.com.br": ("imap.uol.com.br", 993, "smtps.uol.com.br", 465),
    "bol.com.br": ("imap.bol.com.br", 993, "smtps.bol.com.br", 465),
    "terra.com.br": ("imap.terra.com.br", 993, "smtp.terra.com.br", 587),
}


def servidor_sugerido(email):
    dominio = email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""
    return PROVEDORES.get(dominio)


def _preencher(conta):
    sug = servidor_sugerido(conta["email"])
    if sug and not conta.get("smtp_host"):
        conta["smtp_host"], conta["smtp_porta"] = sug[2], sug[3]
    return conta


def carregar_contas():
    """Lista de contas. Lê também o formato antigo, de uma conta só."""
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            dados = json.load(f)
    except (OSError, ValueError):
        return []
    if "contas" in dados:
        lista = dados["contas"]
    elif dados.get("email"):
        lista = [dados]
    else:
        lista = []
    return [_preencher(c) for c in lista if c.get("email")]


def _gravar_contas(contas):
    os.makedirs(PASTA, exist_ok=True)
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump({"contas": contas}, f, ensure_ascii=False, indent=2)


def salvar_conta(conta, senha=None, antigo=None, refresh=None):
    """Adiciona a conta ou, se 'antigo' (e-mail anterior) existir, a substitui.

    'refresh' é o token de renovação do OAuth, guardado no lugar da senha."""
    contas = carregar_contas()
    alvo = antigo or conta["email"]
    for i, c in enumerate(contas):
        if c["email"] == alvo:
            contas[i] = conta
            break
    else:
        contas.append(conta)
    _gravar_contas(contas)
    if senha:
        keyring.set_password(SERVICO, conta["email"], senha)
    if refresh:
        salvar_refresh(conta["email"], refresh)
    if antigo and antigo != conta["email"]:
        _esquecer_senha(antigo)
    if conta.get("auth") != "oauth":
        _esquecer_refresh(conta["email"])  # passou a usar senha


def remover_conta(email):
    _gravar_contas([c for c in carregar_contas() if c["email"] != email])
    _esquecer_senha(email)


def _esquecer_senha(email):
    for usuario in (email, _usuario_oauth(email)):
        try:
            keyring.delete_password(SERVICO, usuario)
        except Exception:  # noqa: BLE001 - não havia nada guardado
            pass


def _esquecer_refresh(email):
    try:
        keyring.delete_password(SERVICO, _usuario_oauth(email))
    except Exception:  # noqa: BLE001 - não havia nada guardado
        pass


def obter_senha(email):
    return keyring.get_password(SERVICO, email) or ""


# O token de renovação do OAuth fica no mesmo cofre, sob outro nome de usuário.
def _usuario_oauth(email):
    return f"{email}#oauth"


def salvar_refresh(email, token):
    keyring.set_password(SERVICO, _usuario_oauth(email), token)


def obter_refresh(email):
    return keyring.get_password(SERVICO, _usuario_oauth(email)) or ""


# ---------- opções do programa (separadas da conta) ----------
ARQUIVO_OPCOES = os.path.join(PASTA, "opcoes.json")


def opcao(chave, padrao):
    try:
        with open(ARQUIVO_OPCOES, encoding="utf-8") as f:
            return json.load(f).get(chave, padrao)
    except (OSError, ValueError):
        return padrao


def salvar_opcao(chave, valor):
    try:
        with open(ARQUIVO_OPCOES, encoding="utf-8") as f:
            opcoes = json.load(f)
    except (OSError, ValueError):
        opcoes = {}
    opcoes[chave] = valor
    os.makedirs(PASTA, exist_ok=True)
    with open(ARQUIVO_OPCOES, "w", encoding="utf-8") as f:
        json.dump(opcoes, f, indent=2)
