"""
Interview Coach - Response Styles
4 response styles: Executive, Commercial, Technical, Mixed
"""
from abc import ABC, abstractmethod
from typing import Optional
from contracts.models import ResponseStyle, QuestionType


class BaseStyle(ABC):
    """Base class for response styles"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Style name"""
        pass
    
    @abstractmethod
    def get_prompt_template(self) -> str:
        """Get the prompt template for this style"""
        pass
    
    @abstractmethod
    def get_structure(self) -> list[str]:
        """Get the response structure for this style"""
        pass
    
    def format_response(self, content: dict) -> str:
        """Format content according to this style"""
        return ""


class ExecutiveStyle(BaseStyle):
    """
    Executive Style: Acción → Método → Resultado con métricas
    
    Rules:
    - Siempre empieza con "Yo" o "En mi rol como..."
    - Al menos UNA métrica cuantificable
    - 150-220 palabras
    """
    
    @property
    def name(self) -> str:
        return "executive"
    
    def get_prompt_template(self) -> str:
        return """Eres un coach de entrevistas. Genera una respuesta en estilo EJECUTIVO.

REGLAS DE ESTILO EJECUTIVO:
1. Estructura: Acción → Método → Resultado con métricas
2. Siempre empieza con "Yo..." o "En mi rol como..."
3. Incluye al menos UNA métrica cuantificable (%, $, tiempo, número)
4. Longitud: 150-220 palabras
5. Tono profesional y directo
6. Lenguaje: {language}

PREGUNTA DEL ENTREVISTADOR:
{question}

EVIDENCIA DEL PERFIL:
{evidence}

CONTEXTO CONVERSACIONAL:
{conversation_context}

MÉTRICAS YA USADAS (NO REPETIR):
{metrics_used}

Genera 3-5 bullets clave seguidos de una respuesta completa."""

    def get_structure(self) -> list[str]:
        return [
            "Apertura directa con tu rol",
            "Acción específica que tomaste",
            "Método o enfoque utilizado",
            "Resultado cuantificable",
            "Conexión con el rol objetivo"
        ]


class CommercialStyle(BaseStyle):
    """
    Commercial Style: Necesidad empresa → Tu prueba → Valor futuro
    
    Rules:
    - Conecta CADA respuesta con el rol
    - Cierra mirando hacia adelante
    - Demuestra understanding de la empresa
    """
    
    @property
    def name(self) -> str:
        return "commercial"
    
    def get_prompt_template(self) -> str:
        return """Eres un coach de entrevistas. Genera una respuesta en estilo COMERCIAL.

REGLAS DE ESTILO COMERCIAL:
1. Estructura: Necesidad empresa → Tu prueba → Valor futuro
2. Empieza reconociendo la necesidad: "Entiendo que [necesidad]..."
3. Conecta CADA punto con el rol al que aplicas
4. Cierra mirando hacia adelante: "Puedo aportar..."
5. Demuestra conocimiento de la empresa
6. Lenguaje: {language}

PREGUNTA DEL ENTREVISTADOR:
{question}

EMPRESA Y ROL:
{company_context}

EVIDENCIA DEL PERFIL:
{evidence}

CONTEXTO CONVERSACIONAL:
{conversation_context}

Genera 3-5 bullets clave seguidos de una respuesta completa."""

    def get_structure(self) -> list[str]:
        return [
            "Reconocimiento de la necesidad",
            "Tu experiencia relevante como prueba",
            "Conexión específica con el rol",
            "Propuesta de valor futuro",
            "Cierre orientado a acción"
        ]


class TechnicalStyle(BaseStyle):
    """
    Technical Style: Problema → Análisis/Trade-offs → Implementación → Outcome
    
    Rules:
    - Usa terminología técnica correcta
    - Menciona herramientas específicas
    - Habla de trade-offs, no solo la solución
    - Conecta lo técnico con impacto en negocio
    """
    
    @property
    def name(self) -> str:
        return "technical"
    
    def get_prompt_template(self) -> str:
        return """Eres un coach de entrevistas técnicas. Genera una respuesta en estilo TÉCNICO.

REGLAS DE ESTILO TÉCNICO:
1. Estructura: Problema → Análisis/Trade-offs → Implementación → Outcome
2. Usa terminología técnica específica y correcta
3. Menciona herramientas y tecnologías por nombre
4. Discute trade-offs y decisiones de diseño
5. Conecta impacto técnico con valor de negocio
6. Sé específico, no vago
7. Lenguaje: {language}

PREGUNTA DEL ENTREVISTADOR:
{question}

STACK TÉCNICO Y EXPERIENCIA:
{technical_context}

EVIDENCIA DEL PERFIL:
{evidence}

CONTEXTO CONVERSACIONAL:
{conversation_context}

Genera 3-5 bullets clave seguidos de una respuesta completa."""

    def get_structure(self) -> list[str]:
        return [
            "Definición del problema técnico",
            "Análisis de opciones y trade-offs",
            "Decisión de implementación",
            "Herramientas y tecnologías usadas",
            "Outcome e impacto en negocio"
        ]


class MixedStyle(BaseStyle):
    """
    Mixed Style: Auto-detecta según QuestionAnalysis.primary_type
    
    Mapping:
    - behavioral → Executive
    - technical → Technical
    - culture fit → Commercial
    - compound → selecciona per sub-question
    """
    
    STYLE_MAP = {
        QuestionType.BEHAVIORAL: ExecutiveStyle,
        QuestionType.TECHNICAL: TechnicalStyle,
        QuestionType.SITUATIONAL: ExecutiveStyle,
        QuestionType.CASUAL: CommercialStyle,
        QuestionType.FOLLOW_UP: ExecutiveStyle,
        QuestionType.STRESS: ExecutiveStyle,
        QuestionType.COMPOUND: ExecutiveStyle,  # Default, can override per sub-question
    }
    
    def __init__(self, primary_type: Optional[QuestionType] = None):
        self.primary_type = primary_type or QuestionType.BEHAVIORAL
        self._delegate = self._get_delegate()
    
    def _get_delegate(self) -> BaseStyle:
        """Get the appropriate style delegate based on question type"""
        style_class = self.STYLE_MAP.get(self.primary_type, ExecutiveStyle)
        return style_class()
    
    @property
    def name(self) -> str:
        return f"mixed({self._delegate.name})"
    
    def get_prompt_template(self) -> str:
        return self._delegate.get_prompt_template()
    
    def get_structure(self) -> list[str]:
        return self._delegate.get_structure()


def get_style(style: ResponseStyle, primary_type: Optional[QuestionType] = None) -> BaseStyle:
    """Factory function to get the appropriate style"""
    styles = {
        ResponseStyle.EXECUTIVE: ExecutiveStyle,
        ResponseStyle.COMMERCIAL: CommercialStyle,
        ResponseStyle.TECHNICAL: TechnicalStyle,
        ResponseStyle.MIXED: lambda: MixedStyle(primary_type),
    }
    
    style_class = styles.get(style, ExecutiveStyle)
    
    if callable(style_class) and style == ResponseStyle.MIXED:
        return style_class()
    
    return style_class()
