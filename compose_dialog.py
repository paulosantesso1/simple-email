"""Janela de escrever mensagem: nova, resposta ou encaminhamento."""
import mimetypes
import os
from email.utils import getaddresses

import wx

import contatos
import mailer
from contatos_dialog import CompletadorContatos, EscolherContatosDialog

ID_RASCUNHO = wx.NewIdRef()


def _enderecos_de(texto):
    """Quebra um texto com um ou vários endereços em itens 'Nome <email>'."""
    return [contatos.formatar({"nome": nome, "email": email})
            for nome, email in getaddresses([texto]) if email]


class CampoEnderecos:
    """Campo Para, Cc ou Cco: digite um endereço e aperte Enter para ele entrar numa lista.
    Na lista, Delete tira os selecionados (Shift+setas e Ctrl+A escolhem vários)."""

    def __init__(self, dialogo, grade, rotulo, inicial=""):
        self.dialogo = dialogo
        self.grade = grade
        self.nome = rotulo.replace("&", "").rstrip(":")
        r = wx.StaticText(dialogo, label=rotulo)
        self.texto = wx.TextCtrl(dialogo, name=self.nome)
        self.texto.AutoComplete(CompletadorContatos())  # sugere contatos ao digitar
        grade.Add(r, 0, wx.ALIGN_CENTER_VERTICAL)
        grade.Add(self.texto, 1, wx.EXPAND)
        self.rotulo_lista = wx.StaticText(dialogo, label=f"Endereços em {self.nome}")
        self.lista = wx.ListBox(dialogo, style=wx.LB_EXTENDED, size=(-1, 64),
                                name=f"Endereços em {self.nome}")
        grade.Add(self.rotulo_lista, 0, wx.ALIGN_CENTER_VERTICAL)
        grade.Add(self.lista, 1, wx.EXPAND)
        self.itens = []
        self.adicionar(_enderecos_de(inicial))
        self.lista.Bind(wx.EVT_KEY_DOWN, self.on_tecla)
        self.texto.Bind(wx.EVT_KILL_FOCUS, self.on_perdeu_foco)

    # ---------- conteúdo ----------
    def valor(self):
        """Todos os endereços como um texto só (inclui o que ainda está sendo digitado)."""
        pendente = self.texto.GetValue().strip()
        return ", ".join(self.itens + ([pendente] if pendente else []))

    def assinatura(self):
        return (tuple(self.itens), self.texto.GetValue())

    def adicionar(self, novos):
        """Põe na lista os endereços que ainda não estão lá. Devolve quantos entraram."""
        ja = {e.lower() for _, e in getaddresses(self.itens)}
        entraram = 0
        for item in novos:
            email = getaddresses([item])[0][1].lower()
            if email and email not in ja:
                ja.add(email)
                self.itens.append(item)
                entraram += 1
        self._atualizar()
        return entraram

    def _atualizar(self, selecionar=0):
        self.lista.Set(self.itens)
        if self.itens:
            self.lista.SetSelection(max(0, min(selecionar, len(self.itens) - 1)))
        for janela in (self.rotulo_lista, self.lista):
            self.grade.Show(janela, bool(self.itens))  # a lista só aparece quando há endereços
        self.dialogo.Layout()

    # ---------- ações ----------
    def confirmar(self):
        """Enter: o que foi digitado vira item da lista. Devolve False se o endereço é inválido."""
        digitado = self.texto.GetValue().strip()
        if not digitado:
            return True
        ruim = mailer.validar_enderecos(digitado)
        if ruim or not mailer.destinatarios(digitado):
            wx.MessageBox(f"O endereço {ruim or digitado} não parece válido.", "Simple Email",
                          wx.OK | wx.ICON_WARNING, self.dialogo)
            self.texto.SetFocus()
            return False
        self.adicionar(_enderecos_de(digitado))
        self.texto.SetValue("")
        return True

    def remover_selecionados(self):
        escolhidos = sorted(self.lista.GetSelections())
        if not escolhidos:
            return
        for i in reversed(escolhidos):
            del self.itens[i]
        if not self.itens:
            self.texto.SetFocus()  # a lista vai sumir; o foco não pode ficar nela
        self._atualizar(escolhidos[0])
        if self.itens:
            self.lista.SetFocus()

    def on_tecla(self, evento):
        k = evento.GetKeyCode()
        if k in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self.remover_selecionados()
        elif evento.ControlDown() and k in (ord("A"), ord("a")):
            for i in range(self.lista.GetCount()):
                self.lista.Select(i)
        else:
            evento.Skip()

    def on_perdeu_foco(self, evento):
        evento.Skip()
        digitado = self.texto.GetValue().strip()
        # Ao sair do campo, o que foi digitado entra na lista, se for um endereço válido.
        if digitado and not mailer.validar_enderecos(digitado) and mailer.destinatarios(digitado):
            wx.CallAfter(self.confirmar)


class ComposeDialog(wx.Dialog):
    """Resultado de ShowModal: wx.ID_OK (enviar), ID_RASCUNHO ou wx.ID_CANCEL.
    Atalhos: Ctrl+Enter envia, Ctrl+S salva rascunho, Esc fecha."""

    def __init__(self, parent, prefill, contas=(), de_padrao=None):
        super().__init__(parent, title="Nova mensagem", size=(850, 760),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.prefill = prefill
        self.anexos = list(prefill.get("anexos", []))
        self.SetTitle(prefill.get("assunto") or "Nova mensagem")

        # Cada rótulo é criado logo antes do seu campo, para o NVDA anunciar o nome.
        grade = wx.FlexGridSizer(2, 6, 8)
        grade.AddGrowableCol(1, 1)
        self.campos = {}
        self.enderecos = {}
        self.de = None
        if contas:
            grade.Add(wx.StaticText(self, label="&De:"), 0, wx.ALIGN_CENTER_VERTICAL)
            self.de = wx.Choice(self, choices=list(contas), name="De")
            self.de.SetSelection(list(contas).index(de_padrao) if de_padrao in contas else 0)
            grade.Add(self.de, 1, wx.EXPAND)
        for chave, rotulo in (("para", "&Para:"), ("cc", "&Cc:"), ("bcc", "Cc&o:")):
            campo = CampoEnderecos(self, grade, rotulo, prefill.get(chave, ""))
            self.enderecos[chave] = campo
            self.campos[chave] = campo.texto
        r = wx.StaticText(self, label="&Assunto:")
        self.campos["assunto"] = wx.TextCtrl(self, value=prefill.get("assunto", ""), name="Assunto")
        grade.Add(r, 0, wx.ALIGN_CENTER_VERTICAL)
        grade.Add(self.campos["assunto"], 1, wx.EXPAND)

        rot_corpo = wx.StaticText(self, label="&Texto da mensagem")
        self.corpo = wx.TextCtrl(self, value=prefill.get("corpo", ""),
                                 style=wx.TE_MULTILINE, name="Texto da mensagem")
        rot_anexos = wx.StaticText(self, label="A&nexos")
        # LB_EXTENDED: Shift+setas e Ctrl+A escolhem vários anexos, como na lista de mensagens.
        self.lista_anexos = wx.ListBox(self, name="Anexos", style=wx.LB_EXTENDED)
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
        self.lista_anexos.Bind(wx.EVT_KEY_DOWN, self.on_tecla_anexos)
        b_enviar.Bind(wx.EVT_BUTTON, self.on_enviar)
        b_rascunho.Bind(wx.EVT_BUTTON, self.on_rascunho)
        b_cancelar.Bind(wx.EVT_BUTTON, self.on_cancelar)
        self.Bind(wx.EVT_CLOSE, self.on_cancelar)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_tecla)

        self.Layout()
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
            tuple(c.assinatura() for c in self.enderecos.values()),
            self.campos["assunto"].GetValue(),
            self.corpo.GetValue(),
            tuple(a["nome"] for a in self.anexos),
        )

    def _atualizar_anexos(self, selecionar=0):
        self.lista_anexos.Set([a["nome"] for a in self.anexos])
        if self.anexos:
            self.lista_anexos.SetSelection(max(0, min(selecionar, len(self.anexos) - 1)))

    def dados(self):
        d = {k: c.valor() for k, c in self.enderecos.items()}
        d["assunto"] = self.campos["assunto"].GetValue().strip()
        d.update(
            de_conta=self.de.GetStringSelection() if self.de else "",
            corpo=self.corpo.GetValue(),
            anexos=self.anexos,
            in_reply_to=self.prefill.get("in_reply_to", ""),
            references=self.prefill.get("references", ""),
        )
        return d

    # ---------- eventos ----------
    def _campo_de_endereco_com_foco(self):
        foco = wx.Window.FindFocus()
        return next((c for c in self.enderecos.values() if c.texto is foco), None)

    def on_tecla(self, evento):
        k = evento.GetKeyCode()
        if evento.ControlDown() and k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_enviar(None)
        elif k in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and self._campo_de_endereco_com_foco():
            self._campo_de_endereco_com_foco().confirmar()  # Enter num endereço: entra na lista
        elif evento.ControlDown() and k in (ord("S"), ord("s")):
            self.on_rascunho(None)
        elif evento.ControlDown() and k in (ord("K"), ord("k")):
            self.on_catalogo(None)
        elif k == wx.WXK_ESCAPE:
            self.on_cancelar(None)
        else:
            evento.Skip()

    def _confirmar_enderecos(self):
        """O que ainda está digitado nos campos de endereço entra nas listas antes de enviar."""
        return all(c.confirmar() for c in self.enderecos.values())

    def on_enviar(self, evento):
        if not self._confirmar_enderecos():
            return
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

    def on_rascunho(self, evento):
        if self._confirmar_enderecos():
            self.EndModal(ID_RASCUNHO)

    def on_cancelar(self, evento):
        if self._assinatura() == self._inicial:
            return self.EndModal(wx.ID_CANCEL)
        dlg = wx.MessageDialog(self, "Esta mensagem foi alterada. O que deseja fazer?",
                               "Simple Email", wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
        dlg.SetYesNoCancelLabels("&Salvar rascunho", "&Descartar", "&Voltar")
        r = dlg.ShowModal()
        dlg.Destroy()
        if r == wx.ID_YES:
            self.on_rascunho(None)
        elif r == wx.ID_NO:
            self.EndModal(wx.ID_CANCEL)

    def on_catalogo(self, evento):
        """Escolhe contatos do catálogo e os coloca na lista de Para, Cc ou Cco."""
        atual = self._campo_de_endereco_com_foco()
        padrao = next((k for k, c in self.enderecos.items() if c is atual), "para")
        dlg = EscolherContatosDialog(self, padrao)
        if dlg.ShowModal() == wx.ID_OK:
            chave, escolhidos = dlg.resultado()
            if escolhidos:
                campo = self.enderecos[chave]
                campo.adicionar(escolhidos)
                dlg.Destroy()
                return campo.texto.SetFocus()
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
            self._atualizar_anexos(len(self.anexos) - 1)
        dlg.Destroy()
        self.lista_anexos.SetFocus()

    def on_tecla_anexos(self, evento):
        k = evento.GetKeyCode()
        if k in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self.on_remover(None)
        elif evento.ControlDown() and k in (ord("A"), ord("a")):
            for i in range(self.lista_anexos.GetCount()):
                self.lista_anexos.Select(i)
        else:
            evento.Skip()

    def on_remover(self, evento):
        """Tira da lista todos os anexos selecionados (botão Remover ou tecla Delete)."""
        escolhidos = sorted(self.lista_anexos.GetSelections())
        if not escolhidos:
            return self._aviso("Selecione um ou mais anexos na lista para remover.", self.lista_anexos)
        for i in reversed(escolhidos):
            del self.anexos[i]
        self._atualizar_anexos(escolhidos[0])  # o foco fica no anexo seguinte, que o NVDA lê
        self.lista_anexos.SetFocus()

    def _aviso(self, texto, campo):
        wx.MessageBox(texto, "Simple Email", wx.OK | wx.ICON_WARNING, self)
        campo.SetFocus()
