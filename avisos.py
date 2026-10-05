"""Avisos curtos, anunciados pelo leitor de tela sem pausar a navegação."""
import wx
import wx.adv

import opcoes_dialog

APP_NAME = "Simple Email"

_notificacoes = []  # o Windows descarta a notificação se o objeto for destruído antes de sumir


def avisar(texto, pai):
    """Aviso curto que o leitor de tela anuncia, sem pausar a navegação.
    Por padrão é uma notificação do sistema que some sozinha em 2 segundos; em Opções dá
    para voltar à janelinha que se fecha sozinha (Enter ou Esc também fecham)."""
    if opcoes_dialog.opcao("avisar_com_notificacao"):
        try:
            n = wx.adv.NotificationMessage(APP_NAME, texto, parent=wx.GetApp().GetTopWindow())
            n.SetFlags(wx.ICON_INFORMATION)
            if n.Show(timeout=wx.adv.NotificationMessage.Timeout_Auto):
                _notificacoes.append(n)

                def sumir():
                    n.Close()
                    if n in _notificacoes:
                        _notificacoes.remove(n)

                wx.CallLater(2000, sumir)
                return
        except Exception:  # noqa: BLE001 - se o sistema não mostrar, cai na janelinha
            pass
    _aviso_em_janela(texto, pai)


def _aviso_em_janela(texto, pai):
    dlg = wx.Dialog(pai, title=APP_NAME)
    rotulo = wx.StaticText(dlg, label=texto)
    ok = wx.Button(dlg, wx.ID_OK, "OK")
    caixa = wx.BoxSizer(wx.VERTICAL)
    caixa.Add(rotulo, 0, wx.ALL, 16)
    caixa.Add(ok, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.ALIGN_CENTER, 16)
    dlg.SetSizerAndFit(caixa)
    dlg.CentreOnParent()
    ok.SetDefault()
    dlg.SetEscapeId(wx.ID_OK)
    wx.CallLater(2000, lambda: dlg.EndModal(wx.ID_OK) if dlg.IsModal() else None)
    dlg.ShowModal()
    dlg.Destroy()
