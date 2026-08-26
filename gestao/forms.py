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
            "envio_resultados",
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
            "email_resultados",
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


class ParcialResultadoForm(forms.Form):
    arquivo = forms.FileField(
        label="Imagem",
        help_text="PNG, JPG ou WEBP. Envio para um PDV ou para todos do escopo.",
    )
    caption = forms.CharField(
        label="Texto / legenda",
        required=False,
        max_length=900,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Texto curto que vai junto da imagem."}
        ),
    )
    parceiro = forms.ModelChoiceField(
        queryset=Parceiro.objects.none(),
        required=False,
        label="PDV",
    )

    def __init__(self, *args, parceiros=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = parceiros if parceiros is not None else Parceiro.objects.filter(ativo=True)
        self.fields["parceiro"].queryset = qs

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome = (arquivo.name or "").lower()
        if not any(nome.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
            raise forms.ValidationError("Use uma imagem PNG, JPG ou WEBP.")
        if arquivo.size and arquivo.size > 8 * 1024 * 1024:
            raise forms.ValidationError("A imagem deve ter no máximo 8 MB.")
        return arquivo


class PracaBTUForm(forms.Form):
    nome = forms.CharField(
        label="Município / praça BTU",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Ipatinga"}),
    )


class GdpImportForm(forms.Form):
    arquivo_b2c = forms.FileField(
        label="GDP B2C",
        required=False,
        help_text="Planilha 20xx_B2C_GDP.xlsx. Aba PAP (Local), portfólio vigente NOVO ESPECIAL.",
    )
    arquivo_b2b = forms.FileField(
        label="GDP B2B",
        required=False,
        help_text="Opcional. Se B2C e B2B divergirem, a união das praças ESPECIAL entra no ranking.",
    )

    def _validar_xlsx(self, arquivo):
        if not arquivo:
            return arquivo
        nome = (arquivo.name or "").lower()
        if not nome.endswith((".xlsx", ".xls", ".xlsb")):
            raise forms.ValidationError("Use o GDP em .xlsx.")
        return arquivo

    def clean_arquivo_b2c(self):
        return self._validar_xlsx(self.cleaned_data.get("arquivo_b2c"))

    def clean_arquivo_b2b(self):
        return self._validar_xlsx(self.cleaned_data.get("arquivo_b2b"))

    def clean(self):
        dados = super().clean()
        if not dados.get("arquivo_b2c") and not dados.get("arquivo_b2b"):
            raise forms.ValidationError("Envie o GDP B2C e/ou o GDP B2B.")
        return dados
