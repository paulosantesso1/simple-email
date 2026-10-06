"""Monta a página HTML exibida na leitura: cabeçalho, links clicáveis e títulos."""
import html
import re

from conversas import titulo_mensagem
from imap_client import encontrar_links

# Sem scripts, sem imagens nem conteúdo remoto: o e-mail não "avisa" o remetente
# que foi aberto, e nada dentro da mensagem executa código.
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'"

ESTILO = (
    "body{font-family:Segoe UI,Arial,sans-serif;font-size:16px;line-height:1.5;"
    "margin:16px;max-width:60em}"
    "h1{font-size:1.4em}dl{margin:0 0 1em}dt{font-weight:bold;float:left;clear:left;"
    "margin-right:.4em}dd{margin:0}h2{font-size:1.15em;margin-bottom:.3em}.texto{white-space:pre-wrap;word-wrap:break-word}"
)


def _texto_com_links(texto):
    """Texto simples escapado, com cada endereço http(s) transformado em link."""
    saida, fim = [], 0
    for m in re.finditer(r"https?://[^\s<>\"')\]]+", texto):
        url = m.group(0).rstrip(".,;:!?")
        saida.append(html.escape(texto[fim:m.start()]))
        saida.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>')
        fim = m.start() + len(url)
    saida.append(html.escape(texto[fim:]))
    return "".join(saida)


def _limpar_html(corpo):
    """Tira o que não deve vir do e-mail: scripts, base, redirecionamentos e a moldura."""
    corpo = re.sub(r"(?is)<(script|object|embed|iframe)\b.*?</\1\s*>", "", corpo)
    corpo = re.sub(r"(?is)<(base|meta|link)\b[^>]*>", "", corpo)
    corpo = re.sub(r"(?is)<title\b.*?</title\s*>", "", corpo)
    m = re.search(r"(?is)<body\b[^>]*>(.*)</body\s*>", corpo)
    return m.group(1) if m else re.sub(r"(?is)</?(html|head|body)\b[^>]*>", "", corpo)


def _montar_conversa(dados):
    """Todas as mensagens da conversa numa página só, cada uma com o seu título (H no NVDA).
    O Para só aparece na primeira, para não repetir a lista de destinatários."""
    msgs = dados["conversa"]
    partes = []
    for k, d in enumerate(msgs, 1):
        cab = []
        if k == 1 and d["para"]:
            cab.append(("Para", d["para"]))
        if d["anexos"]:
            cab.append(("Anexos", "; ".join(d["anexos"])))
        lista = "".join(f"<dt>{r}:</dt><dd>{html.escape(v)}</dd>" for r, v in cab)
        partes.append(
            f"<h2>{html.escape(titulo_mensagem(k, len(msgs), d))}</h2><dl>{lista}</dl>"
            f'<div class="texto">{_texto_com_links(d["texto"])}</div><hr>')
    assunto = html.escape(dados["assunto"])
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<title>{assunto}</title><style>{ESTILO}</style></head><body>"
        f"<h1>{assunto}</h1>{''.join(partes)}</body></html>"
    )


def montar_pagina(dados):
    if dados.get("conversa"):
        return _montar_conversa(dados)
    cab = [("De", dados["de"]), ("Para", dados["para"]), ("Data", dados["data"])]
    if dados["anexos"]:
        cab.append(("Anexos", "; ".join(dados["anexos"])))
    lista = "".join(
        f"<dt>{r}:</dt><dd>{html.escape(v)}</dd>" for r, v in cab if v
    )
    if dados.get("html"):
        corpo = _limpar_html(dados["html"])
    else:
        corpo = f'<div class="texto">{_texto_com_links(dados["texto"])}</div>'
    assunto = html.escape(dados["assunto"])
    return (
        '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        f"<title>{assunto}</title><style>{ESTILO}</style></head><body>"
        f"<h1>{assunto}</h1><dl>{lista}</dl><hr>{corpo}</body></html>"
    )


def links_da_pagina(dados):
    return encontrar_links(dados["texto"])
