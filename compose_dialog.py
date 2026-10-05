"""Janela de escrever mensagem: nova, resposta ou encaminhamento."""
import mimetypes
import os

import wx

import mailer
from contatos_dialog import CompletadorContatos, EscolherContatosDialog

ID_RASCUNHO = wx.NewIdRef()


class ComposeDialog(wx.Dialog):
    """Resultado de ShowModal: wx.ID_OK (enviar), ID_RASCUNHO ou wx.ID_CANCEL.
    Atalhos: Ctrl+Enter envia, Ctrl+S salva rascunho, Esc fecha."""

    def __init__(self, parent, prefill, contas=(), de_padrao=None):
        super().__init__(parent, title="Nova mensagem", size=(850, 700),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.prefill = prefill
        self.anexos = list(prefill.get("anexos", []))
        self.SetTitle(prefill.get("assunto") or "Nova mensagem")

        # Cada rótulo é criado logo antes do seu campo, para o NVDA anunciar o nome.
        grade = wx.FlexGridSizer(2, 6, 8)
        grade.AddGrowableCol(1, 1)
        self.campos = {}
        self.de = None
        if contas:
            grade.Add(wx.StaticText(self, label="&De:"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.de = wx.Choice(self, choices=list(contas), name="De")
            self.de.SetSelection(list(contas).index(de_padrao) if de_padrao in contas else 0)
            grade.Add(self.de, 1, wx.EXPAND)
        for chave, rotulo in (
            ("para", "&Para:"), ("cc", "&Cc:"), ("bcc", "Cc&o:"), ("assunto", "&Assunto:"),
        ):
            r = wx.StaticText(self, label=rotulo)
            c = wx.TextCtrl(self, value=prefill.get(chave, ""),
                            name=rotulo.replace("&", "").rstrip(":"))
            grade.Add(r, 0, wx.ALIGN_CENTER_VERTICAL)
            grade.Add(c, 1, wx.EXPAND)
            self.campos[chave] = c
            if chave in ("para", "cc", "bcc"):
                c.AutoComplete(CompletadorContatos())  # sugere contatos ao digitar

        rot_corpo = wx.StaticText(self, label="&Texto da mensagem")
        self.corpo = wx.TextCtrl(self, value=prefill.get("corpo", ""),
                                 style=wx.TE_MULTILINE, name="Texto da mensagem")
        rot_anexos = wx.StaticText(self, label="A&nexos")
        self.lista_anexos = wx.ListBox(self, name="Anexos")
        self._atualizar_anexos()

        b_catalogo = wx.Button(self, wx.ID_ANY, "Catá&logo de endereços (Ctrl+K)")
        b_anexar = wx.Button(self, wx.ID_ANY, "Anexar a&rquivo...")
        b_remover = wx.Button(self, wx.ID_ANY, "&Remover anexo")
        b_enviar = wx.Button(self, wx.ID_OK, "&Enviar (Ctrl+Enter)")
        b_rascunho = wx.Button(self, ID_RASCUNHO, "Salvar ra&scunho (Ctrl+S)")
        b_cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")

        linha_anexos = wx.BoxSizer(wx.HORIZONTAL)
        linha_anexos.Add(self.lista_anexos, 1, wx.EXPAND | wx.RIGHT, 8)
        col_b = wx.BoxSizer(wx.VERTICAL)
        col_b.Add(b_anexar, 0, wx.BOTTOM, 6)
        col_b.Add(b_remover)
        linha_anexos.Add(col_b)

        botoes = wx.BoxSizer(wx.HORIZONTAL)
        botoes.Add(b_catalogo, 0, wx.LEFT, 8)
        for b in (b_enviar, b_rascunho, b_cancelar):
            botoes.Add(b, 0, wx.LEFT, 8)

        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(grade, 0, wx.EXPAND | wx.ALL, 8)
        raiz.Add(rot_corpo, 0, wx.LEFT | wx.RIGHT, 8)
        raiz.Add(self.corpo, 1, wx.EXPAND | wx.ALL, 8)
        raiz.Add(rot_anexos, 0, wx.LEFT | wx.RIGHT, 8)
        raiz.Add(linha_anexos, 0, wx.EXPAND | wx.ALL, 8)
        raiz.Add(botoes, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(raiz)
        self.SetMinSize((600, 500))

        b_catalogo.Bind(wx.EVT_BUTTON, self.on_catalogo)
        b_anexar.Bind(wx.EVT_BUTTON, self.on_anexar)
        b_remover.Bind(wx.EVT_BUTTON, self.on_remover)
        b_enviar.Bind(wx.EVT_BUTTON, self.on_enviar)
        b_rascunho.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(ID_RASCUNHO))
        b_cancelar.Bind(wx.EVT_BUTTON, self.on_cancelar)
        self.Bind(wx.EVT_CLOSE, self.on_cancelar)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_tecla)

        self._inicial = self._assinatura()
        if prefill.get("para"):
            self.corpo.SetFocus()
            self.corpo.SetInsertionPoint(0)
        else:
            self.campos["para"].SetFocus()

    # ---------- estado ----------
    def _assinatura(self):
        return (
            self.de.GetSelection() if self.de else 0,
            tuple(c.GetValue() for c in self.campos.values()),
            self.corpo.GetValue(),
            tuple(a["nome"] for a in self.anexos),
        )

    def _atualizar_anexos(self):
        self.lista_anexos.Set([a["nome"] for a in self.anexos])
        if self.anexos:
            self.lista_anexos.SetSelection(0)

    def dados(self):
        d = {k: c.GetValue().strip() for k, c in self.campos.items()}
        d.update(
            de_conta=self.de.GetStringSelection() if self.de else "",
            corpo=self.corpo.GetValue(),
            anexos=self.anexos,
            in_reply_to=self.prefill.get("in_reply_to", ""),
            references=self.prefill.get("references", ""),
        )
        return d

    # ---------- eventos ----------
    def on_tecla(self, evento):
        k = evento.GetKeyCode()
        if evento.ControlDown() and k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_enviar(None)
        elif evento.ControlDown() and k in (ord("S"), ord("s")):
            self.EndModal(ID_RASCUNHO)
        elif evento.ControlDown() and k in (ord("K"), ord("k")):
            self.on_catalogo(None)
        elif k == wx.WXK_ESCAPE:
            self.on_cancelar(None)
        else:
            evento.Skip()

    def on_enviar(self, evento):
        d = self.dados()
        if not (d["para"] or d["cc"] or d["bcc"]):
            return self._aviso("Digite pelo menos um destinatário.", self.campos["para"])
        for chave in ("para", "cc", "bcc"):
            ruim = mailer.validar_enderecos(d[chave])
            if ruim:
                return self._aviso(f"O endereço {ruim} não parece válido.", self.campos[chave])
        if not d["assunto"]:
            r = wx.MessageBox("A mensagem está sem assunto. Enviar mesmo assim?",
                              "Simple Email", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self)
            if r != wx.YES:
                return self.campos["assunto"].SetFocus()
        self.EndModal(wx.ID_OK)

    def on_cancelar(self, evento):
        if self._assinatura() == self._inicial:
            return self.EndModal(wx.ID_CANCEL)
        dlg = wx.MessageDialog(self, "Esta mensagem foi alterada. O que deseja fazer?",
                               "Simple Email", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        dlg.SetYesNoCancelLabels("&Salvar rascunho", "&Descartar", "&Voltar")
        r = dlg.ShowModal()
        dlg.Destroy()
        if r == wx.ID_YES:
            self.EndModal(ID_RASCUNHO)
        elif r == wx.ID_NO:
            self.EndModal(wx.ID_CANCEL)

    def on_catalogo(self, evento):
        """Escolhe contatos do catálogo e os coloca no campo Para, Cc ou Cco."""
        foco = wx.Window.FindFocus()
        padrao = next((k for k, c in self.campos.items() if c is foco and k != "assunto"), "para")
        dlg = EscolherContatosDialog(self, padrao)
        if dlg.ShowModal() == wx.ID_OK:
            chave, escolhidos = dlg.resultado()
            if escolhidos:
                campo = self.campos[chave]
                atual = campo.GetValue().strip().rstrip(",;")
                campo.SetValue(", ".join(([atual] if atual else []) + escolhidos))
                campo.SetInsertionPointEnd()
                dlg.Destroy()
                return campo.SetFocus()
        dlg.Destroy()

    def on_anexar(self, evento):
        dlg = wx.FileDialog(self, "Escolha os arquivos para anexar",
                            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            for caminho in dlg.GetPaths():
                tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
                principal, _, sub = tipo.partition("/")
                self.anexos.append({"nome": os.path.basename(caminho), "caminho": caminho,
                                    "tipo": (principal, sub), "dados": None})
            self._atualizar_anexos()
            self.lista_anexos.SetSelection(len(self.anexos) - 1)
        dlg.Destroy()
        self.lista_anexos.SetFocus()

    def on_remover(self, evento):
        i = self.lista_anexos.GetSelection()
        if i == wx.NOT_FOUND:
            return self._aviso("Selecione um anexo na lista para remover.", self.lista_anexos)
        del self.anexos[i]
        self._atualizar_anexos()
        self.lista_anexos.SetFocus()

    def _aviso(self, texto, campo):
        wx.MessageBox(texto, "Simple Email", wx.OK | wx.ICON_WARNING, self)
        campo.SetFocus()
