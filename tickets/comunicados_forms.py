from __future__ import annotations

from django import forms

from .models import Comunicado


class ComunicadoForm(forms.ModelForm):
    class Meta:
        model = Comunicado
        fields = ["titulo", "corpo", "publico", "ativo"]
        widgets = {
            "titulo": forms.TextInput(attrs={"maxlength": 180}),
            "corpo": forms.Textarea(attrs={"rows": 14}),
        }
        help_texts = {
            "publico": (
                "Parceiros confirmam no login do PDV. Equipe confirma no login interno. "
                "Todos exige confirmação dos dois públicos."
            ),
            "ativo": "Desmarque para arquivar. Comunicados inativos não bloqueiam o login.",
        }
