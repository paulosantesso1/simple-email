"""Catálogo de endereços: contatos (nome e e-mail) guardados em um arquivo JSON."""
import json
import os
import re

import config

ARQUIVO = os.path.join(config.PASTA, "contatos.json")


def carregar():
    try:
        with open(ARQUIVO, encoding="utf-8") as f:
            lista = json.load(f)
    except (OSError, ValueError):
        return []
    contatos = [{"nome": str(c.get("nome", "")), "email": str(c["email"])}
                for c in lista if isinstance(c, dict) and c.get("email")]
    return sorted(contatos, key=_chave)


def _chave(c):
    return (c["nome"] or c["email"]).lower()


def _gravar(contatos):
    os.makedirs(config.PASTA, exist_ok=True)
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(sorted(contatos, key=_chave), f, ensure_ascii=False, indent=2)


def existe(email):
    return any(c["email"].lower() == email.lower() for c in carregar())


def salvar(nome, email, antigo_email=None):
    """Adiciona o contato ou, se 'antigo_email' for dado, altera aquele contato.
    Devolve False se o e-mail novo já pertence a outro contato."""
    contatos = carregar()
    alvo = (antigo_email or email).lower()
    if email.lower() != alvo and any(c["email"].lower() == email.lower() for c in contatos):
        return False
    novo = {"nome": nome.strip(), "email": email.strip()}
    for i, c in enumerate(contatos):
        if c["email"].lower() == alvo:
            contatos[i] = novo
            break
    else:
        contatos.append(novo)
    _gravar(contatos)
    return True


def apagar(email):
    _gravar([c for c in carregar() if c["email"].lower() != email.lower()])


def formatar(c):
    """Como o contato aparece nos campos Para, Cc e Cco: Nome <email>."""
    if not c["nome"]:
        return c["email"]
    nome = c["nome"].replace('"', "")
    if re.search(r"[,;:<>@()\[\]\.]", nome):
        nome = f'"{nome}"'
    return f"{nome} <{c['email']}>"  # sem codificação, para aparecer legível no campo


def rotulo(c):
    """Texto lido na lista: nome e endereço, ou só o endereço."""
    return f"{c['nome']}, {c['email']}" if c["nome"] else c["email"]


def buscar(texto, limite=10):
    """Contatos cujo nome ou e-mail começam (em alguma palavra) com o texto digitado."""
    texto = texto.strip().lower()
    if not texto:
        return []
    padrao = re.compile(r"(^|[\s.<@_-])" + re.escape(texto))
    return [c for c in carregar()
            if padrao.search(c["nome"].lower()) or padrao.search(c["email"].lower())][:limite]
