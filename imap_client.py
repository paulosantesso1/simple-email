"""Acesso ao servidor por IMAP: pastas, lista de mensagens e leitura do texto."""
import base64
import email
import imaplib
import re
import threading
import time
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

LIMITE_MENSAGENS = 100
ESPERA_APOS_LOGIN_RECUSADO = 30 * 60  # segundos

NOMES_POR_FLAG = {
    "\\sent": "Enviados",
    "\\trash": "Lixeira",
    "\\junk": "Spam",
    "\\drafts": "Rascunhos",
    "\\all": "Todos os e-mails",
    "\\archive": "Arquivo",
    "\\flagged": "Com estrela",
}
NOMES_POR_NOME = {
    "sent": "Enviados", "sent items": "Enviados", "sent messages": "Enviados",
    "enviados": "Enviados", "itens enviados": "Enviados",
    "trash": "Lixeira", "deleted items": "Lixeira", "deleted messages": "Lixeira",
    "lixeira": "Lixeira", "itens excluídos": "Lixeira", "itens excluidos": "Lixeira",
    "junk": "Spam", "junk email": "Spam", "junk e-mail": "Spam", "spam": "Spam",
    "bulk mail": "Spam", "lixo eletrônico": "Spam", "lixo eletronico": "Spam",
    "drafts": "Rascunhos", "draft": "Rascunhos", "rascunhos": "Rascunhos",
}
ORDEM = ["Caixa de Entrada", "Rascunhos", "Enviados", "Spam", "Lixeira"]


# ---------- nomes de pasta (UTF-7 modificado do IMAP) ----------
def decodificar_utf7(s):
    def troca(m):
        t = m.group(1)
        if not t:
            return "&"
        b64 = t.replace(",", "/")
        b64 += "=" * (-len(b64) % 4)
        return base64.b64decode(b64).decode("utf-16-be")
    return re.sub(r"&([^-]*)-", troca, s)


def codificar_utf7(s):
    saida, buf = [], ""

    def descarrega():
        nonlocal buf
        if buf:
            b64 = base64.b64encode(buf.encode("utf-16-be")).decode().rstrip("=")
            saida.append("&" + b64.replace("/", ",") + "-")
            buf = ""

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            descarrega()
            saida.append("&-" if ch == "&" else ch)
        else:
            buf += ch
    descarrega()
    return "".join(saida)


def _citar(raw):
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------- texto da mensagem ----------
class _HtmlParaTexto(HTMLParser):
    """Converte HTML em texto simples, mantendo o endereço dos links e os títulos."""
    BLOCOS = {"p", "div", "br", "tr", "table", "ul", "ol"}
    TITULOS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes, self.ignorar = [], 0
        self.href = None
        self.texto_link = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignorar += 1
        elif tag in self.TITULOS:
            self.partes.append("\n\n")
        elif tag in self.BLOCOS:
            self.partes.append("\n")
        elif tag == "li":
            self.partes.append("\n- ")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self.href = href if href.lower().startswith(("http://", "https://")) else None
            self.texto_link = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.ignorar = max(0, self.ignorar - 1)
        elif tag in self.TITULOS:
            self.partes.append("\n\n")
        elif tag in self.BLOCOS:
            self.partes.append("\n")
        elif tag == "a" and self.href:
            visivel = "".join(self.texto_link).strip()
            if self.href not in visivel:
                self.partes.append(f" ({self.href})")
            self.href = None

    def handle_data(self, data):
        if not self.ignorar:
            self.partes.append(data)
            if self.href:
                self.texto_link.append(data)


def html_para_texto(html):
    p = _HtmlParaTexto()
    p.feed(html)
    texto = "".join(p.partes)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" ?\n ?", "\n", texto)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def encontrar_links(texto):
    """Endereços http(s) do texto, sem repetição, na ordem em que aparecem."""
    vistos = []
    for m in re.finditer(r"https?://[^\s<>\"')\]]+", texto):
        url = m.group(0).rstrip(".,;:!?")
        if url not in vistos:
            vistos.append(url)
    return vistos


def _formatar_data(valor):
    try:
        return parsedate_to_datetime(valor).astimezone().strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return valor or ""


def _remetente(valor):
    nome, endereco = parseaddr(valor or "")
    return nome or endereco or "(sem remetente)"


def _resumo(cabecalhos, uid, flags):
    msg = email.message_from_bytes(cabecalhos, policy=policy.default)
    return {
        "uid": uid,
        "remetente": _remetente(str(msg["from"] or "")),
        "assunto": str(msg["subject"] or "").replace("\r", " ").replace("\n", " ")
        or "(sem assunto)",
        "data": _formatar_data(str(msg["date"] or "")),
        "lida": "\\seen" in flags.lower(),
    }


class ImapClient:
    def __init__(self):
        self.conn = None
        self.lock = threading.RLock()
        self.host = self.porta = self.usuario = self.senha = None
        self.login_recusado = None  # (erro, quando): o servidor recusou o login

    def configurar(self, host, porta, usuario, senha):
        with self.lock:
            self._fechar()
            self.login_recusado = None
            self.host, self.porta, self.usuario, self.senha = host, porta, usuario, senha

    def _fechar(self):
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass
        self.conn = None

    def _chamar(self, fn):
        with self.lock:
            if self.login_recusado and time.time() - self.login_recusado[1] < ESPERA_APOS_LOGIN_RECUSADO:
                raise self.login_recusado[0]
            for tentativa in (0, 1):
                try:
                    if self.conn is None:
                        c = imaplib.IMAP4_SSL(self.host, self.porta, timeout=30)
                        try:
                            c.login(self.usuario, self.senha)
                        except imaplib.IMAP4.error as e:
                            self.login_recusado = (e, time.time())
                            raise
                        self.conn = c
                    return fn(self.conn)
                except (imaplib.IMAP4.abort, OSError):
                    self.conn = None
                    if tentativa:
                        raise
                except imaplib.IMAP4.error:
                    self._fechar()
                    raise

    def _selecionar(self, c, raw):
        tipo, dados = c.select(_citar(raw))
        if tipo != "OK":
            raise imaplib.IMAP4.error(f"Não foi possível abrir a pasta: {dados}")

    # ---------- pastas ----------
    def listar_pastas(self):
        def f(c):
            tipo, dados = c.list()
            if tipo != "OK":
                raise imaplib.IMAP4.error("Não foi possível listar as pastas.")
            pastas = []
            for item in dados:
                if item is None:
                    continue
                if isinstance(item, tuple):
                    cabeca, nome_literal = item[0].decode("utf-8", "replace"), item[1].decode()
                    linha, nome = cabeca, nome_literal
                else:
                    linha, nome = item.decode("utf-8", "replace"), None
                m = re.match(
                    r'\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<nome>.*)$',
                    linha,
                )
                if not m:
                    continue
                flags = m.group("flags").lower().split()
                if "\\noselect" in flags or "\\nonexistent" in flags:
                    continue
                if nome is None:
                    nome = m.group("nome").strip()
                    if nome.startswith('"') and nome.endswith('"'):
                        nome = re.sub(r"\\(.)", r"\1", nome[1:-1])
                pastas.append(self._descrever(nome, flags, m.group("delim")))
            return sorted(pastas, key=self._chave_ordem)
        return self._chamar(f)

    @staticmethod
    def _descrever(raw, flags, delim="NIL"):
        decod = decodificar_utf7(raw)
        if raw.upper() == "INBOX":
            exibicao = "Caixa de Entrada"
        else:
            exibicao = next((NOMES_POR_FLAG[x] for x in flags if x in NOMES_POR_FLAG), None)
            if not exibicao:
                ultimo = re.split(r"[/.]", decod)[-1].strip().lower()
                exibicao = NOMES_POR_NOME.get(ultimo, decod)
        delim = None if delim.upper() == "NIL" else re.sub(r"\\(.)", r"\1", delim[1:-1])
        protegida = (
            raw.upper() == "INBOX"
            or exibicao in ORDEM
            or any(f in NOMES_POR_FLAG for f in flags)
        )
        return {"raw": raw, "nome": exibicao, "decod": decod, "delim": delim,
                "protegida": protegida}

    @staticmethod
    def _chave_ordem(p):
        n = p["nome"]
        return (ORDEM.index(n), "") if n in ORDEM else (len(ORDEM), n.lower())

    def guardar(self, raw, conteudo, flags):
        """Grava uma mensagem pronta (rascunho ou cópia de enviado) numa pasta."""
        def f(c):
            tipo, dados = c.append(_citar(raw), flags, imaplib.Time2Internaldate(time.time()), conteudo)
            if tipo != "OK":
                raise imaplib.IMAP4.error(f"Não foi possível gravar na pasta: {dados}")
        self._chamar(f)

    # ---------- organização (uma ou várias mensagens, por UID) ----------
    @staticmethod
    def _conjunto(uids):
        return str(uids) if isinstance(uids, int) else ",".join(str(u) for u in uids)

    def _remover(self, c, uids):
        """Marca como apagadas e remove de vez da pasta aberta."""
        conjunto = self._conjunto(uids)
        c.uid("STORE", conjunto, "+FLAGS", "(\\Deleted)")
        if "UIDPLUS" in c.capabilities:
            c.uid("EXPUNGE", conjunto)
        else:
            c.expunge()

    def apagar_definitivo(self, raw, uids):
        def f(c):
            self._selecionar(c, raw)
            self._remover(c, uids)
        self._chamar(f)

    def esvaziar_pasta(self, raw):
        """Apaga de vez todas as mensagens da pasta. Devolve quantas eram."""
        def f(c):
            tipo, dados = c.select(_citar(raw))
            if tipo != "OK":
                raise imaplib.IMAP4.error(f"Não foi possível abrir a pasta: {dados}")
            total = int(dados[0] or 0)
            if total:
                c.store("1:*", "+FLAGS", "(\\Deleted)")
                c.expunge()
            return total
        return self._chamar(f)

    def mover(self, raw, uids, destino):
        def f(c):
            self._selecionar(c, raw)
            tipo, dados = c.uid("COPY", self._conjunto(uids), _citar(destino))
            if tipo != "OK":
                raise imaplib.IMAP4.error(f"Não foi possível copiar: {dados}")
            self._remover(c, uids)
        self._chamar(f)

    def marcar_lida(self, raw, uids, lida):
        def f(c):
            self._selecionar(c, raw)
            c.uid("STORE", self._conjunto(uids), "+FLAGS" if lida else "-FLAGS", "(\\Seen)")
        self._chamar(f)

    def _comando_pasta(self, nome_comando, *args):
        def f(c):
            tipo, dados = getattr(c, nome_comando)(*args)
            if tipo != "OK":
                raise imaplib.IMAP4.error(f"O servidor recusou: {dados}")
        self._chamar(f)

    def criar_pasta(self, nome):
        self._comando_pasta("create", _citar(codificar_utf7(nome)))
        return codificar_utf7(nome)

    def renomear_pasta(self, raw, delim, novo_nome):
        prefixo = raw.rsplit(delim, 1)[0] + delim if delim and delim in raw else ""
        novo_raw = prefixo + codificar_utf7(novo_nome)
        self._comando_pasta("rename", _citar(raw), _citar(novo_raw))
        return novo_raw

    def apagar_pasta(self, raw):
        def f(c):
            if c.state == "SELECTED":  # algumas contas não apagam a pasta que está aberta
                c.close()
            tipo, dados = c.delete(_citar(raw))
            if tipo != "OK":
                raise imaplib.IMAP4.error(f"O servidor recusou: {dados}")
        self._chamar(f)

    # ---------- mensagens ----------
    def sincronizar(self, raw, conhecidos, limite=LIMITE_MENSAGENS):
        """Compara a pasta do servidor com o que já temos: baixa só os cabeçalhos das
        mensagens novas e o estado lida/não lida de todas as recentes."""
        def f(c):
            self._selecionar(c, raw)
            resp = c.response("UIDVALIDITY")[1]
            validade = resp[0].decode() if resp and resp[0] else ""
            tipo, dados = c.uid("SEARCH", None, "ALL")
            if tipo != "OK":
                raise imaplib.IMAP4.error("Falha ao buscar mensagens.")
            uids = [int(u) for u in dados[0].split()][-limite:]
            novos = [u for u in uids if u not in conhecidos]
            return {
                "validade": validade,
                "uids": uids,
                "novos": self._cabecalhos(c, novos),
                "flags": self._flags(c, uids),
            }
        return self._chamar(f)

    @staticmethod
    def _registros(dados):
        registros = []
        for item in dados:
            if isinstance(item, tuple):
                registros.append([item[0].decode("utf-8", "replace"), item[1]])
            elif isinstance(item, bytes):
                texto = item.decode("utf-8", "replace")
                if registros and not re.match(r"\s*\d+ \(", texto):
                    registros[-1][0] += " " + texto  # continuação (ex.: FLAGS depois do literal)
                else:
                    registros.append([texto, b""])
        return registros

    def _cabecalhos(self, c, uids):
        mensagens = []
        for k in range(0, len(uids), 50):
            conjunto = self._conjunto(uids[k:k + 50])
            tipo, dados = c.uid(
                "FETCH", conjunto,
                "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
            )
            if tipo != "OK":
                raise imaplib.IMAP4.error("Falha ao ler os cabeçalhos.")
            for meta, cab in self._registros(dados):
                uid = re.search(r"UID (\d+)", meta)
                flags = re.search(r"FLAGS \(([^)]*)\)", meta)
                if uid:
                    mensagens.append(
                        _resumo(cab, int(uid.group(1)), flags.group(1) if flags else ""))
        return mensagens

    def _flags(self, c, uids):
        resultado = {}
        for k in range(0, len(uids), 200):
            tipo, dados = c.uid("FETCH", self._conjunto(uids[k:k + 200]), "(FLAGS)")
            if tipo != "OK":
                raise imaplib.IMAP4.error("Falha ao ler o estado das mensagens.")
            for meta, _ in self._registros(dados):
                uid = re.search(r"UID (\d+)", meta)
                flags = re.search(r"FLAGS \(([^)]*)\)", meta)
                if uid and flags:
                    resultado[int(uid.group(1))] = "\\seen" in flags.group(1).lower()
        return resultado

    def baixar(self, raw, uid):
        """Baixa a mensagem inteira (bytes) e a marca como lida no servidor."""
        def f(c):
            self._selecionar(c, raw)
            tipo, dados = c.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if tipo != "OK" or not dados or not isinstance(dados[0], tuple):
                raise imaplib.IMAP4.error("Não foi possível baixar a mensagem.")
            conteudo = dados[0][1]
            c.uid("STORE", str(uid), "+FLAGS", "(\\Seen)")
            return conteudo
        return self._chamar(f)

    def ler_mensagem(self, raw, uid):
        return self.interpretar(self.baixar(raw, uid))

    @classmethod
    def interpretar(cls, conteudo):
        msg = email.message_from_bytes(conteudo, policy=policy.default)
        return {
            "de": str(msg["from"] or ""),
            "para": str(msg["to"] or ""),
            "cc": str(msg["cc"] or ""),
            "id": str(msg["message-id"] or ""),
            "referencias": str(msg["references"] or ""),
            "responder_para": str(msg["reply-to"] or ""),
            "raw": conteudo,
            "assunto": str(msg["subject"] or "(sem assunto)"),
            "data": _formatar_data(str(msg["date"] or "")),
            "texto": cls._extrair_texto(msg),
            "html": cls._extrair_html(msg),
            "anexos": [a.get_filename() or "(sem nome)" for a in msg.iter_attachments()],
        }

    @staticmethod
    def _extrair_html(msg):
        try:
            parte = msg.get_body(preferencelist=("html",))
            return parte.get_content() if parte is not None else None
        except Exception:
            return None

    @staticmethod
    def _extrair_texto(msg):
        try:
            corpo = msg.get_body(preferencelist=("plain", "html"))
            if corpo is None:
                return "(Esta mensagem não tem texto.)"
            conteudo = corpo.get_content()
            if corpo.get_content_type() == "text/html":
                conteudo = html_para_texto(conteudo)
            return conteudo.replace("\r\n", "\n").strip() or "(Mensagem vazia.)"
        except Exception:
            return "(Não foi possível ler o texto desta mensagem.)"
