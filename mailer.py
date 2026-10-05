"""Montagem e envio de mensagens (SMTP), respostas e encaminhamentos."""
import email
import re
import smtplib
import ssl
from email import policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid

import oauth


def _prefixar(assunto, tipo):
    padrao = r"(?i)^(re|res)\s*:" if tipo == "re" else r"(?i)^(fwd?|enc)\s*:"
    assunto = assunto.strip()
    if re.match(padrao, assunto):
        return assunto
    return ("Re: " if tipo == "re" else "Fwd: ") + assunto


def anexos_originais(raw):
    """Anexos de uma mensagem baixada, para reaproveitar ao encaminhar."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    lista = []
    for parte in msg.iter_attachments():
        dados = parte.get_payload(decode=True)
        if dados is None:
            dados = parte.as_bytes()
        principal, _, sub = parte.get_content_type().partition("/")
        lista.append({
            "nome": parte.get_filename() or "anexo",
            "caminho": None,
            "tipo": (principal, sub or "octet-stream"),
            "dados": dados,
        })
    return lista


def preparar(acao, dados, meu_email):
    """Dados iniciais da janela de escrever para 'responder', 'todos' ou 'encaminhar'."""
    de = dados["responder_para"] or dados["de"]
    cabecalho = (
        f"De: {dados['de']}\nData: {dados['data']}\n"
        f"Assunto: {dados['assunto']}\nPara: {dados['para']}\n"
    )
    if acao == "encaminhar":
        return {
            "assunto": _prefixar(dados["assunto"], "fwd"),
            "corpo": f"\n\n---------- Mensagem encaminhada ----------\n{cabecalho}\n{dados['texto']}",
            "anexos": anexos_originais(dados["raw"]),
        }
    citado = "\n".join("> " + linha for linha in dados["texto"].splitlines())
    prefill = {
        "para": de,
        "assunto": _prefixar(dados["assunto"], "re"),
        "corpo": f"\n\nEm {dados['data']}, {dados['de']} escreveu:\n{citado}\n",
        "in_reply_to": dados["id"],
        "references": f"{dados['referencias']} {dados['id']}".strip(),
        "anexos": [],
    }
    if acao == "todos":
        ja = {e.lower() for _, e in getaddresses([de])} | {meu_email.lower()}
        outros = []
        for nome, end in getaddresses([dados["para"], dados["cc"]]):
            if end and end.lower() not in ja:
                ja.add(end.lower())
                outros.append(formataddr((nome, end)))
        prefill["cc"] = ", ".join(outros)
    return prefill


def de_rascunho(dados):
    """Dados iniciais da janela de escrever a partir de um rascunho salvo no servidor."""
    msg = email.message_from_bytes(dados["raw"], policy=policy.default)
    return {
        "para": str(msg["to"] or ""),
        "cc": str(msg["cc"] or ""),
        "bcc": str(msg["bcc"] or ""),
        "assunto": dados["assunto"],
        "corpo": dados["texto"],
        "in_reply_to": str(msg["in-reply-to"] or ""),
        "references": str(msg["references"] or ""),
        "anexos": anexos_originais(dados["raw"]),
    }


def destinatarios(texto):
    return [e for _, e in getaddresses([texto]) if e]


def validar_enderecos(texto):
    """Devolve o primeiro endereço que não parece válido, ou None."""
    for _, end in getaddresses([texto]):
        if end and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", end):
            return end
    return None


def montar(conta, d, incluir_bcc=False):
    msg = EmailMessage()
    msg["From"] = formataddr((conta.get("nome", ""), conta["email"]))
    if d.get("para"):
        msg["To"] = d["para"]
    if d.get("cc"):
        msg["Cc"] = d["cc"]
    if incluir_bcc and d.get("bcc"):
        msg["Bcc"] = d["bcc"]
    msg["Subject"] = d.get("assunto", "")
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=conta["email"].rsplit("@", 1)[-1])
    if d.get("in_reply_to"):
        msg["In-Reply-To"] = d["in_reply_to"]
    if d.get("references"):
        msg["References"] = d["references"]
    msg.set_content(d.get("corpo", ""))
    for a in d.get("anexos", []):
        dados = a["dados"]
        if dados is None:
            with open(a["caminho"], "rb") as f:
                dados = f.read()
        principal, sub = a["tipo"]
        msg.add_attachment(dados, maintype=principal, subtype=sub, filename=a["nome"])
    return msg


def enviar(conta, senha, msg, destinos):
    host, porta = conta["smtp_host"], int(conta["smtp_porta"])
    cadeia = None
    if conta.get("auth") == "oauth":
        cadeia = oauth.cadeia_xoauth2(conta["email"], oauth.token_de_acesso(conta))
    contexto = ssl.create_default_context()
    if porta == 465:
        servidor = smtplib.SMTP_SSL(host, porta, context=contexto, timeout=30)
    else:
        servidor = smtplib.SMTP(host, porta, timeout=30)
    with servidor:
        if porta != 465:
            servidor.starttls(context=contexto)
        if cadeia:
            servidor.auth("XOAUTH2", oauth.autenticador(cadeia), initial_response_ok=True)
        else:
            servidor.login(conta["email"], senha)
        servidor.send_message(msg, to_addrs=destinos)
