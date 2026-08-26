from __future__ import annotations

import re

from django import forms

from tickets.models import Parceiro

from .models import Destinatario


class DestinatarioForm(forms.ModelForm):
    class Meta:
        model = Destinatario
        fields = (
            "parceiro",
            "nome",
            "jid",
            "tipo",
            "ativo",
            "prioridade",
            "envio_osab",
            "envio_capilaridade",
            "envio_fpd",
            "envio_fpd_critico",
            "envio_churn",
            "envio_comissionamento",
            "envio_tarefas",
            "envio_venda_indevida",
            "envio_recompra",
            "email",
            "email_osab",
            "email_capilaridade",
            "email_fpd",
            "email_fpd_critico",
            "email_churn",
            "email_comissionamento",
            "email_tarefas",
            "email_venda_indevida",
            "email_recompra",
            "razoes_sociais_comissionamento",
        )
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "Ex.: Grupo Inova / João"}),
            "jid": forms.TextInput(
                attrs={"placeholder": "5531999999999 ou 120363...@g.us", "class": "mono"}
            ),
            "prioridade": forms.NumberInput(attrs={"min": 1}),
            "razoes_sociais_comissionamento": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Uma razão social por linha (ou ;)\nEx.: LUISA SERVICOS DE TELEFONIA...",
                }
            ),
        }

    def clean_jid(self):
        jid = (self.cleaned_data.get("jid") or "").strip()
        if not jid:
            raise forms.ValidationError("Informe o número ou o JID do grupo.")
        if "@" in jid:
            return jid
        digitos = re.sub(r"\D", "", jid)
        if not digitos:
            raise forms.ValidationError(
                "JID inválido. Use o número com DDI (ex.: 5531999999999) "
                "ou o JID do grupo (…@g.us) — não o nome do contato."
            )
        return jid


class UploadBaseForm(forms.Form):
    arquivo = forms.FileField(label="Arquivo")

    def __init__(self, *args, extensoes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.extensoes = extensoes or [".xlsx", ".xlsb", ".xls"]
        self.fields["arquivo"].help_text = "Formatos: " + ", ".join(self.extensoes)

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome = (arquivo.name or "").lower()
        if not any(nome.endswith(ext) for ext in self.extensoes):
            raise forms.ValidationError("Formato inválido. Use " + ", ".join(self.extensoes))
        return arquivo


class PeriodoForm(forms.Form):
    ano = forms.IntegerField(min_value=2020, max_value=2100, label="Ano")
    mes = forms.IntegerField(min_value=1, max_value=12, label="Mês")


class GrossForm(forms.Form):
    parceiro = forms.ModelChoiceField(queryset=Parceiro.objects.filter(ativo=True), label="Parceiro")
    anomes = forms.IntegerField(
        min_value=202001,
        max_value=210012,
        label="Safra (AAAAMM)",
        help_text="Ex.: 202507",
    )
    gross = forms.IntegerField(min_value=0, label="Gross")
