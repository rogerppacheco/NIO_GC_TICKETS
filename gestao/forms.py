from __future__ import annotations

from django import forms

from tickets.models import Parceiro


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
