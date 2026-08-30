from __future__ import annotations

from django import forms
from django.utils.text import slugify

from .models import ProcessoAnexo, ProcessoLink, ProcessoRepositorio


class ProcessoRepositorioForm(forms.ModelForm):
    class Meta:
        model = ProcessoRepositorio
        fields = [
            "titulo",
            "categoria",
            "resumo",
            "finalidade",
            "quando_usar",
            "encaminhamento",
            "canal",
            "email_destino",
            "email_cc_especialista",
            "email_cc_extra",
            "requer_planilha",
            "instrucoes_planilha",
            "passos",
            "tags",
            "publico",
            "ordem",
            "ativo",
        ]
        widgets = {
            "finalidade": forms.Textarea(attrs={"rows": 3}),
            "quando_usar": forms.Textarea(attrs={"rows": 3}),
            "encaminhamento": forms.Textarea(attrs={"rows": 2}),
            "instrucoes_planilha": forms.Textarea(attrs={"rows": 2}),
            "passos": forms.Textarea(attrs={"rows": 5}),
        }

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            base = slugify(obj.titulo)[:100] or "processo"
            slug = base
            n = 1
            while ProcessoRepositorio.objects.filter(slug=slug).exclude(pk=obj.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            obj.slug = slug
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class ProcessoAnexoForm(forms.ModelForm):
    class Meta:
        model = ProcessoAnexo
        fields = ["titulo", "arquivo", "tipo", "ordem"]


class ProcessoLinkForm(forms.ModelForm):
    class Meta:
        model = ProcessoLink
        fields = ["titulo", "url", "ordem"]
