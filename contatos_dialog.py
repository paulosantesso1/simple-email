"""Janelas do catálogo de endereços."""
from email.utils import parseaddr

import wx

import contatos
import mailer

APP_NAME = "Simple Email"


class CompletadorContatos(wx.TextCompleterSimple):
    """Sugere contatos enquanto se digita nos campos Para, Cc e Cco.
    Vale para o último endereço do campo, depois da última vírgula."""

    def GetCompletions(self, prefixo):
        corte = max(prefixo.rfind(","), prefixo.rfind(";"))
        antes = prefixo[:corte + 1] + (" " if corte >= 0 else "")
        return [antes + contatos.formatar(c) for c in contatos.buscar(prefixo[corte + 1:])]


class ContatoDialog(wx.Dialog):
    """Nome e e-mail de um contato."""

    def __init__(self, parent, nome="", email="", titulo="Novo contato"):
        super().__init__(parent, title=titulo)
        grade = wx.FlexGridSizer(2, 8, 8)
        grade.AddGrowableCol(1, 1)
        r1 = wx.StaticText(self, label="&Nome:")
        self.nome = wx.TextCtrl(self, value=nome, name="Nome", size=(320, -1))
        r2 = wx.StaticText(self, label="&E-mail:")
        self.email = wx.TextCtrl(self, value=email, name="E-mail")
        for r, c in ((r1, self.nome), (r2, self.email)):
            grade.Add(r, 0, wx.ALIGN_CENTER_VERTICAL)
            grade.Add(c, 1, wx.EXPAND)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(grade, 0, wx.EXPAND | wx.ALL, 12)
        raiz.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(raiz)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        (self.nome if not nome and not email else self.email).SetFocus()

    def on_ok(self, evento):
        email = self.email.GetValue().strip()
        if not email or mailer.validar_enderecos(email) or "@" not in email:
            wx.MessageBox("Digite um endereço de e-mail válido.", APP_NAME,
                          wx.OK | wx.ICON_WARNING, self)
            return self.email.SetFocus()
        evento.Skip()

    def resultado(self):
        return self.nome.GetValue().strip(), self.email.GetValue().strip()


def novo_contato(parent, nome="", email=""):
    """Abre a janela de novo contato e grava. Devolve True se gravou."""
    dlg = ContatoDialog(parent, nome, email)
    gravou = False
    while dlg.ShowModal() == wx.ID_OK:
        n, e = dlg.resultado()
        if contatos.existe(e):
            wx.MessageBox("Esse e-mail já está no catálogo.", APP_NAME,
                          wx.OK | wx.ICON_INFORMATION, dlg)
            continue
        gravou = contatos.salvar(n, e)
        break
    dlg.Destroy()
    return gravou


def salvar_remetente(parent, de):
    """Guarda o remetente de uma mensagem ('Nome <email>') no catálogo, depois de confirmar."""
    nome, endereco = parseaddr(de or "")
    if not endereco:
        return wx.MessageBox("Não consegui ler o endereço do remetente.", APP_NAME,
                             wx.OK | wx.ICON_WARNING, parent)
    if contatos.existe(endereco):
        return wx.MessageBox(f"{endereco} já está no catálogo de endereços.", APP_NAME,
                             wx.OK | wx.ICON_INFORMATION, parent)
    if novo_contato(parent, nome, endereco):
        wx.MessageBox("Contato salvo no catálogo de endereços.", APP_NAME,
                      wx.OK | wx.ICON_INFORMATION, parent)


class ContatosDialog(wx.Dialog):
    """Ferramentas > Catálogo de endereços: ver, adicionar, editar e apagar contatos."""

    def __init__(self, parent):
        super().__init__(parent, title="Catálogo de endereços",
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        rotulo = wx.StaticText(self, label="C&ontatos")
        self.lista = wx.ListBox(self, name="Contatos", size=(460, 280))
        b_add = wx.Button(self, wx.ID_ANY, "&Adicionar...")
        b_edit = wx.Button(self, wx.ID_ANY, "&Editar...")
        b_del = wx.Button(self, wx.ID_ANY, "Ap&agar")
        fechar = wx.Button(self, wx.ID_CANCEL, "&Fechar")
        col = wx.BoxSizer(wx.VERTICAL)
        for b in (b_add, b_edit, b_del, fechar):
            col.Add(b, 0, wx.EXPAND | wx.BOTTOM, 6)
        linha = wx.BoxSizer(wx.HORIZONTAL)
        linha.Add(self.lista, 1, wx.EXPAND | wx.RIGHT, 8)
        linha.Add(col)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(linha, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizerAndFit(raiz)
        self.SetEscapeId(wx.ID_CANCEL)
        b_add.Bind(wx.EVT_BUTTON, self.on_adicionar)
        b_edit.Bind(wx.EVT_BUTTON, self.on_editar)
        b_del.Bind(wx.EVT_BUTTON, self.on_apagar)
        self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self.on_editar)
        self.lista.Bind(wx.EVT_KEY_DOWN, self.on_tecla)
        self.atualizar()
        self.lista.SetFocus()

    def atualizar(self, selecionar_email=None, posicao=0):
        self.itens = contatos.carregar()
        self.lista.Set([contatos.rotulo(c) for c in self.itens])
        if not self.itens:
            return
        i = next((n for n, c in enumerate(self.itens)
                  if selecionar_email and c["email"].lower() == selecionar_email.lower()), None)
        self.lista.SetSelection(i if i is not None else min(posicao, len(self.itens) - 1))

    def _atual(self):
        i = self.lista.GetSelection()
        return (i, self.itens[i]) if i != wx.NOT_FOUND else (None, None)

    def on_tecla(self, evento):
        if evento.GetKeyCode() == wx.WXK_DELETE:
            self.on_apagar(None)
        else:
            evento.Skip()

    def on_adicionar(self, evento):
        dlg = ContatoDialog(self)
        while dlg.ShowModal() == wx.ID_OK:
            nome, email = dlg.resultado()
            if contatos.existe(email):
                wx.MessageBox("Esse e-mail já está no catálogo.", APP_NAME,
                              wx.OK | wx.ICON_INFORMATION, dlg)
                continue
            contatos.salvar(nome, email)
            self.atualizar(email)
            break
        dlg.Destroy()
        self.lista.SetFocus()

    def on_editar(self, evento):
        i, c = self._atual()
        if c is None:
            return
        dlg = ContatoDialog(self, c["nome"], c["email"], "Editar contato")
        while dlg.ShowModal() == wx.ID_OK:
            nome, email = dlg.resultado()
            if not contatos.salvar(nome, email, antigo_email=c["email"]):
                wx.MessageBox("Esse e-mail já pertence a outro contato.", APP_NAME,
                              wx.OK | wx.ICON_INFORMATION, dlg)
                continue
            self.atualizar(email)
            break
        dlg.Destroy()
        self.lista.SetFocus()

    def on_apagar(self, evento):
        i, c = self._atual()
        if c is None:
            return
        r = wx.MessageBox(f"Apagar o contato {contatos.rotulo(c)}?", APP_NAME,
                          wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
        if r == wx.YES:
            contatos.apagar(c["email"])
            self.atualizar(posicao=i)
        self.lista.SetFocus()


class EscolherContatosDialog(wx.Dialog):
    """Escolhe vários contatos de uma vez para colocar em Para, Cc ou Cco."""
    CAMPOS = (("para", "Para"), ("cc", "Cc"), ("bcc", "Cco"))

    def __init__(self, parent, campo_padrao="para"):
        super().__init__(parent, title="Escolher contatos")
        self.itens = contatos.carregar()
        rotulo = wx.StaticText(self, label="C&ontatos (Shift ou Ctrl para escolher vários)")
        self.lista = wx.ListBox(self, choices=[contatos.rotulo(c) for c in self.itens],
                                style=wx.LB_EXTENDED, name="Contatos", size=(460, 240))
        r2 = wx.StaticText(self, label="&Adicionar em:")
        self.campo = wx.Choice(self, choices=[n for _, n in self.CAMPOS], name="Adicionar em")
        self.campo.SetSelection(next((i for i, (k, _) in enumerate(self.CAMPOS)
                                      if k == campo_padrao), 0))
        linha = wx.BoxSizer(wx.HORIZONTAL)
        linha.Add(r2, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        linha.Add(self.campo)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        raiz.Add(linha, 0, wx.ALL, 8)
        raiz.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizerAndFit(raiz)
        if self.itens:
            self.lista.SetSelection(0)
        self.lista.SetFocus()

    def resultado(self):
        """(chave do campo, endereços formatados) dos contatos escolhidos."""
        escolhidos = [contatos.formatar(self.itens[i]) for i in self.lista.GetSelections()]
        return self.CAMPOS[self.campo.GetSelection()][0], escolhidos
