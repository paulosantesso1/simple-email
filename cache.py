"""Cópia local dos e-mails em SQLite: a janela abre na hora e só busca o que mudou."""
import os
import sqlite3
import threading

import config

TAMANHO_MAXIMO_CORPO = 15 * 1024 * 1024  # mensagens maiores que isso não ficam na cópia local


class Cache:
    def __init__(self, caminho=None):
        caminho = caminho or os.path.join(config.PASTA, "cache.db")
        if caminho != ":memory:":
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(caminho, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pastas(
                    conta TEXT, ordem INTEGER, raw TEXT, nome TEXT, decod TEXT,
                    delim TEXT, protegida INTEGER, validade TEXT,
                    PRIMARY KEY(conta, raw));
                CREATE TABLE IF NOT EXISTS mensagens(
                    conta TEXT, pasta TEXT, uid INTEGER, remetente TEXT, assunto TEXT,
                    data TEXT, lida INTEGER,
                    PRIMARY KEY(conta, pasta, uid));
                CREATE TABLE IF NOT EXISTS corpos(
                    conta TEXT, pasta TEXT, uid INTEGER, raw BLOB,
                    PRIMARY KEY(conta, pasta, uid));
                """
            )

    # ---------- pastas ----------
    def pastas(self, conta):
        with self.lock:
            linhas = self.db.execute(
                "SELECT * FROM pastas WHERE conta=? ORDER BY ordem", (conta,)).fetchall()
        return [{"raw": r["raw"], "nome": r["nome"], "decod": r["decod"], "delim": r["delim"],
                 "protegida": bool(r["protegida"])} for r in linhas]

    def salvar_pastas(self, conta, pastas):
        """Grava a lista do servidor e descarta o que sumiu (pasta apagada ou renomeada)."""
        with self.lock, self.db:
            for i, p in enumerate(pastas):
                self.db.execute(
                    "INSERT INTO pastas(conta, ordem, raw, nome, decod, delim, protegida)"
                    " VALUES(?,?,?,?,?,?,?)"
                    " ON CONFLICT(conta, raw) DO UPDATE SET ordem=excluded.ordem,"
                    " nome=excluded.nome, decod=excluded.decod, delim=excluded.delim,"
                    " protegida=excluded.protegida",
                    (conta, i, p["raw"], p["nome"], p["decod"], p["delim"], int(p["protegida"])))
            marcas = ",".join("?" * len(pastas))
            raws = [p["raw"] for p in pastas]
            for tabela, coluna in (("pastas", "raw"), ("mensagens", "pasta"), ("corpos", "pasta")):
                self.db.execute(
                    f"DELETE FROM {tabela} WHERE conta=? AND {coluna} NOT IN ({marcas})",
                    [conta] + raws)

    def validade(self, conta, pasta):
        with self.lock:
            r = self.db.execute("SELECT validade FROM pastas WHERE conta=? AND raw=?",
                                (conta, pasta)).fetchone()
        return r["validade"] if r else None

    def limpar_pasta(self, conta, pasta):
        with self.lock, self.db:
            for tabela in ("mensagens", "corpos"):
                self.db.execute(f"DELETE FROM {tabela} WHERE conta=? AND pasta=?", (conta, pasta))
            self.db.execute("UPDATE pastas SET validade=NULL WHERE conta=? AND raw=?",
                            (conta, pasta))

    def remover_conta(self, conta):
        with self.lock, self.db:
            for tabela in ("pastas", "mensagens", "corpos"):
                self.db.execute(f"DELETE FROM {tabela} WHERE conta=?", (conta,))

    # ---------- mensagens ----------
    def mensagens(self, conta, pasta):
        with self.lock:
            linhas = self.db.execute(
                "SELECT uid, remetente, assunto, data, lida FROM mensagens"
                " WHERE conta=? AND pasta=? ORDER BY uid DESC", (conta, pasta)).fetchall()
        return [{"uid": r["uid"], "remetente": r["remetente"], "assunto": r["assunto"],
                 "data": r["data"], "lida": bool(r["lida"])} for r in linhas]

    def uids(self, conta, pasta):
        with self.lock:
            return {r["uid"] for r in self.db.execute(
                "SELECT uid FROM mensagens WHERE conta=? AND pasta=?", (conta, pasta))}

    def aplicar_sincronizacao(self, conta, pasta, r):
        """r: resultado de ImapClient.sincronizar (validade, uids, novos, flags)."""
        with self.lock, self.db:
            self.db.execute("UPDATE pastas SET validade=? WHERE conta=? AND raw=?",
                            (r["validade"], conta, pasta))
            for m in r["novos"]:
                self.db.execute(
                    "INSERT OR REPLACE INTO mensagens VALUES(?,?,?,?,?,?,?)",
                    (conta, pasta, m["uid"], m["remetente"], m["assunto"], m["data"],
                     int(m["lida"])))
            for uid, lida in r["flags"].items():
                self.db.execute(
                    "UPDATE mensagens SET lida=? WHERE conta=? AND pasta=? AND uid=?",
                    (int(lida), conta, pasta, uid))
            # sumiu do servidor (apagada em outro aparelho) ou saiu da janela das mais recentes
            for uid in self.uids(conta, pasta) - set(r["uids"]):
                self._remover_um(conta, pasta, uid)

    def _remover_um(self, conta, pasta, uid):
        for tabela in ("mensagens", "corpos"):
            self.db.execute(f"DELETE FROM {tabela} WHERE conta=? AND pasta=? AND uid=?",
                            (conta, pasta, uid))

    def remover(self, conta, pasta, uids):
        with self.lock, self.db:
            for uid in uids:
                self._remover_um(conta, pasta, uid)

    def marcar_lida(self, conta, pasta, uids, lida):
        with self.lock, self.db:
            for uid in ([uids] if isinstance(uids, int) else uids):
                self.db.execute(
                    "UPDATE mensagens SET lida=? WHERE conta=? AND pasta=? AND uid=?",
                    (int(lida), conta, pasta, uid))

    # ---------- texto completo ----------
    def corpo(self, conta, pasta, uid):
        with self.lock:
            r = self.db.execute("SELECT raw FROM corpos WHERE conta=? AND pasta=? AND uid=?",
                                (conta, pasta, uid)).fetchone()
        return bytes(r["raw"]) if r else None

    def guardar_corpo(self, conta, pasta, uid, raw):
        if len(raw) > TAMANHO_MAXIMO_CORPO:
            return
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO corpos VALUES(?,?,?,?)",
                            (conta, pasta, uid, raw))
