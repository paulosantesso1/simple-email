"""Agrupamento de mensagens da mesma conversa (mesmo assunto, ignorando Re:, Fwd: etc.)."""
import re

_PREFIXO = re.compile(r"^\s*(?:re|res|rv|fwd?|enc|aw|wg)\s*(?:\[\d+\])?\s*:\s*", re.I)


def assunto_base(assunto):
    """Assunto sem os prefixos de resposta e encaminhamento, para comparar conversas."""
    s = assunto or ""
    while True:
        novo = _PREFIXO.sub("", s, count=1)
        if novo == s:
            break
        s = novo
    return " ".join(s.split()).casefold()


def atualizar(linha):
    linha["nao_lidas"] = sum(1 for x in linha["grupo"] if not x["lida"])
    linha["lida"] = linha["nao_lidas"] == 0


def _linha(grupo):
    grupo.sort(key=lambda x: x["uid"], reverse=True)
    nova, antiga = grupo[0], grupo[-1]
    linha = {**nova, "assunto": antiga["assunto"], "grupo": grupo}
    atualizar(linha)
    return linha


def agrupar(msgs, ativo=True):
    """Linhas da lista a partir das mensagens (da mais nova para a mais antiga). Cada linha é a
    mensagem mais nova da conversa mais a chave 'grupo', com todas as mensagens dela.
    Sem agrupar, cada mensagem é uma linha de um grupo só."""
    grupos, por_assunto = [], {}
    for m in msgs:
        chave = assunto_base(m["assunto"]) if ativo else ""
        if chave and chave != "(sem assunto)":
            if chave in por_assunto:
                por_assunto[chave].append(m)
                continue
            por_assunto[chave] = grupo = [m]
        else:
            grupo = [m]
        grupos.append(grupo)
    return [_linha(g) for g in grupos]


def todas(linhas):
    """Todas as mensagens das linhas dadas (as conversas inteiras)."""
    return [x for linha in linhas for x in linha["grupo"]]


def definir_lida(linha, lida):
    for x in linha["grupo"]:
        x["lida"] = lida
    atualizar(linha)


def marcar_lida_uid(linha, uid):
    """Marca como lida a mensagem de UID dado, se for desta linha. Devolve se era."""
    for x in linha["grupo"]:
        if x["uid"] == uid:
            x["lida"] = True
            atualizar(linha)
            return True
    return False


def titulo_mensagem(k, total, d):
    return f"Mensagem {k} de {total}: {d['de']}, {d['data']}"


def juntar(lista, antigas_primeiro=True):
    """Uma 'mensagem' só com a conversa inteira. 'lista' são os dados completos de cada
    mensagem, da mais nova para a mais antiga. Responder ou encaminhar vale para a mais nova."""
    ordem = list(reversed(lista)) if antigas_primeiro else list(lista)
    blocos = []
    for k, d in enumerate(ordem, 1):
        blocos.append(f"{titulo_mensagem(k, len(ordem), d)}\n{d['texto']}")
    return {
        **lista[0],
        "conversa": ordem,
        "texto": "\n\n".join(blocos),
        "html": None,
        "anexos": [nome for d in ordem for nome in d["anexos"]],
    }
