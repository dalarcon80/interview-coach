"""
Interview Coach - Question Analyzer
Deep analysis of interview questions with sub-question decomposition

Analyzes:
- Primary question type (behavioral, technical, situational, etc.)
- Compound question decomposition
- Underlying intent (what interviewer really wants to know)
- Red flags (what to avoid)
- Recommended response style
- Response structure with timing
"""
import os
import json
import re
from typing import Optional
from dataclasses import dataclass

from contracts.models import (
    QuestionType,
    ResponseStyle,
    Priority,
    SubQuestion,
    QuestionAnalysis,
)
from observability.latency import time_step


# Question type detection patterns
QUESTION_PATTERNS = {
    QuestionType.BEHAVIORAL: [
        r"tell me about",
        r"describe a (time|situation)",
        r"give me an example",
        r"walk me through",
        r"cuéntame sobre",
        r"describe una (situación|vez)",
        r"dame un ejemplo",
    ],
    QuestionType.TECHNICAL: [
        r"how (would|do) you",
        r"explain how",
        r"what is your approach",
        r"design a",
        r"architect",
        r"scaling",
        r"technical",
        r"cómo (harías|abordarías)",
        r"explica",
        r"diseña",
    ],
    QuestionType.SITUATIONAL: [
        r"what would you do if",
        r"how would you handle",
        r"imagine",
        r"suppose",
        r"qué harías si",
        r"cómo manejarías",
    ],
    QuestionType.STRESS: [
        r"disagree with",
        r"failed",
        r"mistake",
        r"weakness",
        r"worst",
        r"challenge",
        r"conflict",
        r"if you had to choose",
        r"desacuerdo",
        r"error",
        r"debilidad",
    ],
    QuestionType.FOLLOW_UP: [
        r"you mentioned",
        r"can you elaborate",
        r"tell me more about",
        r"going back to",
        r"mencionaste",
        r"puedes elaborar",
        r"cuéntame más",
    ],
    QuestionType.COMPOUND: [
        r".* and .*",
        r".* además .*",
        r"para eso",
        r"which must",
        r"la cual debe",
    ],
}


@dataclass
class AnalysisContext:
    """Context for question analysis"""
    role_title: str = ""
    company_name: str = ""
    job_description: str = ""
    company_industry: str = ""
    company_description: str = ""
    company_requirements: list[str] = None
    company_culture: str = ""
    candidate_summary: str = ""
    candidate_skills: list[str] = None
    candidate_achievements: list[str] = None
    candidate_certifications: list[str] = None
    conversation_history: list[dict] = None  # HR-2: conversation history for context
    topics_covered: list[str] = None
    metrics_used: list[str] = None
    
    def __post_init__(self):
        if self.company_requirements is None:
            self.company_requirements = []
        if self.candidate_skills is None:
            self.candidate_skills = []
        if self.candidate_achievements is None:
            self.candidate_achievements = []
        if self.candidate_certifications is None:
            self.candidate_certifications = []
        if self.conversation_history is None:
            self.conversation_history = []
        if self.topics_covered is None:
            self.topics_covered = []
        if self.metrics_used is None:
            self.metrics_used = []


class QuestionAnalyzer:
    """
    Deep question analyzer for interview questions.
    
    Features:
    - Detects question type (behavioral, technical, etc.)
    - Decomposes compound questions into sub-questions
    - Identifies underlying intent
    - Flags potential traps (red flags)
    - Recommends response style and structure
    """
    
    def __init__(self, use_llm: bool = True):
        """
        Initialize analyzer.
        
        Args:
            use_llm: Whether to use LLM for deep analysis (vs heuristics only)
        """
        self.use_llm = use_llm
    
    async def analyze(
        self,
        question: str,
        context: Optional[AnalysisContext] = None,
    ) -> QuestionAnalysis:
        """
        Analyze an interview question.
        
        Args:
            question: The interviewer's question/utterance
            context: Additional context (role, company, history)
        
        Returns:
            QuestionAnalysis with type, sub-questions, intent, etc.
        """
        with time_step("question_analysis"):
            # Start with heuristics
            primary_type = self._detect_primary_type(question)
            is_compound = self._detect_compound(question)
            
            # Extract sub-questions if compound
            sub_questions = []
            if is_compound:
                sub_questions = self._decompose_compound(question)
            
            # Extract key topics
            key_topics = self._extract_topics(question, context)
            
            # Identify underlying intent
            underlying_intent = self._identify_intent(question, primary_type, context)
            
            # Identify red flags
            red_flags = self._identify_red_flags(question, primary_type)
            
            # Check if related to previous
            related_to_previous = False
            builds_on_exchange = None
            
            # Recommend style
            recommended_style = self._recommend_style(primary_type, context)
            
            # Generate response structure
            response_structure = self._generate_structure(
                primary_type, sub_questions, recommended_style
            )
            
            return QuestionAnalysis(
                primary_type=primary_type,
                is_compound=is_compound,
                sub_questions=sub_questions,
                key_topics=key_topics,
                underlying_intent=underlying_intent,
                red_flags=red_flags,
                related_to_previous=related_to_previous,
                builds_on_exchange=builds_on_exchange,
                recommended_style=recommended_style,
                response_structure=response_structure,
                confidence=0.85 if not self.use_llm else 0.95,
            )
    
    def _detect_primary_type(self, question: str) -> QuestionType:
        """Detect the primary question type using pattern matching"""
        question_lower = question.lower()
        
        # Check each type's patterns
        type_scores = {}
        for qtype, patterns in QUESTION_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, question_lower, re.IGNORECASE):
                    score += 1
            type_scores[qtype] = score
        
        # Get the type with highest score
        if not any(type_scores.values()):
            return QuestionType.BEHAVIORAL  # Default
        
        return max(type_scores, key=type_scores.get)
    
    def _detect_compound(self, question: str) -> bool:
        """Detect if this is a compound (multi-part) question"""
        # Multiple sentences or clauses
        sentences = re.split(r'[.!?]', question)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) > 2:
            return True
        
        # Check for multiple question words
        question_words = re.findall(
            r'\b(what|how|why|when|where|who|which|tell|describe|explain|qué|cómo|por qué|cuándo|dónde|quién|cuál)\b',
            question.lower()
        )
        
        if len(question_words) > 2:
            return True
        
        # Check for connector words indicating multiple parts
        connectors = ['and', 'also', 'additionally', 'furthermore', 'y', 'además', 'también']
        question_lower = question.lower()
        connector_count = sum(1 for c in connectors if c in question_lower)
        
        return connector_count >= 2
    
    def _decompose_compound(self, question: str) -> list[SubQuestion]:
        """Decompose a compound question into sub-questions"""
        sub_questions = []
        
        # Split by sentence boundaries
        sentences = re.split(r'[.!?]', question)
        sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 10]
        
        # If we have clear sentences, use them
        if len(sentences) > 1:
            for i, sentence in enumerate(sentences):
                # Determine type for each
                sq_type = self._detect_primary_type(sentence)
                
                # Determine priority based on position and content
                priority = Priority.SHOULD_ANSWER
                if i == 0:
                    priority = Priority.MUST_ANSWER
                elif "experience" in sentence.lower() or "experiencia" in sentence.lower():
                    priority = Priority.MUST_ANSWER
                elif "tell me about" in sentence.lower() or "cuéntame" in sentence.lower():
                    priority = Priority.MUST_ANSWER
                
                # Calculate weight based on length and priority
                weight = 0.5
                if priority == Priority.MUST_ANSWER:
                    weight = 0.8 + (0.1 * (len(sentences) - i - 1) / len(sentences))
                elif priority == Priority.SHOULD_ANSWER:
                    weight = 0.5 + (0.2 * (len(sentences) - i) / len(sentences))
                
                sub_questions.append(SubQuestion(
                    text=sentence,
                    type=sq_type,
                    priority=priority,
                    weight=min(weight, 1.0),
                ))
        else:
            # Try to split by clauses
            clauses = re.split(r',\s*(?:and|y|but|pero)\s+', question)
            clauses = [c.strip() for c in clauses if c.strip() and len(c.strip()) > 10]
            
            if len(clauses) > 1:
                for i, clause in enumerate(clauses):
                    priority = Priority.MUST_ANSWER if i == 0 else Priority.SHOULD_ANSWER
                    sub_questions.append(SubQuestion(
                        text=clause,
                        type=self._detect_primary_type(clause),
                        priority=priority,
                        weight=0.7 if priority == Priority.MUST_ANSWER else 0.4,
                    ))
        
        # If still no sub-questions, create one from the whole question
        if not sub_questions:
            sub_questions.append(SubQuestion(
                text=question,
                type=self._detect_primary_type(question),
                priority=Priority.MUST_ANSWER,
                weight=1.0,
            ))
        
        return sub_questions
    
    def _extract_topics(
        self,
        question: str,
        context: Optional[AnalysisContext],
    ) -> list[str]:
        """Extract key topics from the question"""
        topics = []
        
        # Leadership/management topics
        leadership_keywords = [
            "team", "lead", "manage", "scale", "hire", "build",
            "equipo", "liderar", "gestionar", "escalar", "contratar", "construir",
        ]
        if any(kw in question.lower() for kw in leadership_keywords):
            topics.append("leadership")
        
        # Technical topics
        tech_keywords = [
            "architecture", "design", "scale", "performance", "security",
            "arquitectura", "diseño", "escalabilidad", "rendimiento", "seguridad",
        ]
        if any(kw in question.lower() for kw in tech_keywords):
            topics.append("technical")
        
        # Process/methodology topics
        process_keywords = [
            "process", "methodology", "framework", "approach",
            "proceso", "metodología", "marco", "enfoque",
        ]
        if any(kw in question.lower() for kw in process_keywords):
            topics.append("process")
        
        # Experience/background topics
        exp_keywords = [
            "experience", "background", "career", "journey",
            "experiencia", "trayectoria", "carrera",
        ]
        if any(kw in question.lower() for kw in exp_keywords):
            topics.append("experience")
        
        # Results/impact topics
        results_keywords = [
            "result", "impact", "outcome", "metric", "achieve",
            "resultado", "impacto", "métrica", "lograr",
        ]
        if any(kw in question.lower() for kw in results_keywords):
            topics.append("results")
        
        # Add role-specific topics from context
        if context and context.job_description:
            if "cto" in context.job_description.lower():
                topics.append("executive_leadership")
            if "startup" in context.job_description.lower():
                topics.append("startup_environment")

        # Add company requirement-driven topics from context
        if context and context.company_requirements:
            requirements_text = " ".join(context.company_requirements).lower()
            if any(kw in requirements_text for kw in ["architecture", "microservices", "scalability", "security"]):
                topics.append("technical")
            if any(kw in requirements_text for kw in ["lead", "team", "mentor", "stakeholder"]):
                topics.append("leadership")

        # Add candidate skill-driven topic hints
        if context and context.candidate_skills:
            skills_text = " ".join(context.candidate_skills).lower()
            if any(kw in skills_text for kw in ["python", "aws", "architecture", "backend", "distributed"]):
                topics.append("technical")
 
        return list(set(topics))  # Remove duplicates
    
    def _identify_intent(
        self,
        question: str,
        primary_type: QuestionType,
        context: Optional[AnalysisContext],
    ) -> list[str]:
        """Identify the underlying intent of the question"""
        intents = []
        question_lower = question.lower()
        
        # Common intents
        if "experience" in question_lower or "experiencia" in question_lower:
            intents.append("Assess seniority level and relevance")
        
        if "scale" in question_lower or "escalar" in question_lower:
            intents.append("Evaluate ability to grow organizations")
        
        if "challenge" in question_lower or "desafío" in question_lower:
            intents.append("Test problem-solving and resilience")
        
        if "why" in question_lower or "por qué" in question_lower:
            intents.append("Understand motivation and decision-making")
        
        if "fail" in question_lower or "error" in question_lower or "mistake" in question_lower:
            intents.append("Assess self-awareness and learning ability")
        
        if "conflict" in question_lower or "disagree" in question_lower:
            intents.append("Test interpersonal skills and diplomacy")
        
        if primary_type == QuestionType.TECHNICAL:
            intents.append("Verify technical depth and expertise")
        
        if primary_type == QuestionType.BEHAVIORAL:
            intents.append("Predict future performance from past behavior")
        
        if primary_type == QuestionType.STRESS:
            intents.append("Test composure under pressure")
        
        # Add context-specific intents
        if context:
            if "cto" in context.role_title.lower():
                intents.append("Assess executive presence and strategic thinking")

            if context.company_requirements:
                intents.append("Assess fit against explicit role requirements")

            if context.company_culture:
                intents.append("Assess culture and collaboration fit")
 
        return intents if intents else ["Understand candidate's capabilities"]
    
    def _identify_red_flags(
        self,
        question: str,
        primary_type: QuestionType,
    ) -> list[str]:
        """Identify potential traps or things to avoid"""
        flags = []
        question_lower = question.lower()
        
        # Check for negative framing
        if "fail" in question_lower or "error" in question_lower:
            flags.append("Don't blame others for the failure")
            flags.append("Don't claim you never make mistakes")
        
        if "weakness" in question_lower or "debilidad" in question_lower:
            flags.append("Avoid cliché answers like 'I work too hard'")
            flags.append("Don't mention critical skill gaps for the role")
        
        if "disagree" in question_lower or "conflict" in question_lower:
            flags.append("Don't speak negatively about former colleagues")
            flags.append("Don't avoid the question or change the subject")
        
        if "why" in question_lower and ("leave" in question_lower or "left" in question_lower):
            flags.append("Don't speak negatively about previous employer")
            flags.append("Don't focus only on negatives")
        
        if primary_type == QuestionType.STRESS:
            flags.append("Stay calm and professional")
            flags.append("Don't become defensive")
        
        # Compound question red flags
        if primary_type == QuestionType.COMPOUND:
            flags.append("Make sure to address all parts of the question")
            flags.append("Don't spend too much time on one aspect")
        
        return flags
    
    def _check_follow_up(
        self,
        question: str,
        history: list[str],
    ) -> tuple[bool, Optional[int]]:
        """Check if this is a follow-up to a previous exchange"""
        question_lower = question.lower()
        
        # Follow-up indicators
        follow_up_patterns = [
            r"you mentioned",
            r"you said",
            r"going back to",
            r"earlier you",
            r"can you (elaborate|expand|tell me more)",
            r"mencionaste",
            "dijiste",
            "volviendo a",
            "puedes elaborar",
        ]
        
        for pattern in follow_up_patterns:
            if re.search(pattern, question_lower):
                # This is a follow-up - try to identify which exchange
                # For now, assume it's the last one
                return True, len(history) - 1
        
        return False, None
    
    def _recommend_style(
        self,
        primary_type: QuestionType,
        context: Optional[AnalysisContext],
    ) -> ResponseStyle:
        """Recommend a response style based on question type and context"""
        # Style mapping by question type
        style_map = {
            QuestionType.BEHAVIORAL: ResponseStyle.EXECUTIVE,
            QuestionType.TECHNICAL: ResponseStyle.TECHNICAL,
            QuestionType.SITUATIONAL: ResponseStyle.EXECUTIVE,
            QuestionType.STRESS: ResponseStyle.EXECUTIVE,
            QuestionType.FOLLOW_UP: ResponseStyle.EXECUTIVE,
            QuestionType.COMPOUND: ResponseStyle.MIXED,
            QuestionType.CASUAL: ResponseStyle.COMMERCIAL,
        }
        
        base_style = style_map.get(primary_type, ResponseStyle.MIXED)
        
        # Override with context if needed
        if context and context.job_description:
            if "commercial" in context.job_description.lower():
                return ResponseStyle.COMMERCIAL
            if "technical" in context.job_description.lower():
                return ResponseStyle.TECHNICAL

        # Consider explicit requirements/culture hints
        if context and context.company_requirements:
            requirements_text = " ".join(context.company_requirements).lower()
            if any(kw in requirements_text for kw in ["sales", "revenue", "go-to-market", "customer"]):
                return ResponseStyle.COMMERCIAL
            if any(kw in requirements_text for kw in ["architecture", "scalability", "system design", "technical"]):
                return ResponseStyle.TECHNICAL
 
        return base_style
    
    def _generate_structure(
        self,
        primary_type: QuestionType,
        sub_questions: list[SubQuestion],
        style: ResponseStyle,
    ) -> list[str]:
        """Generate recommended response structure with timing"""
        structure = []
        
        if style == ResponseStyle.EXECUTIVE:
            structure = [
                "Context (10%): Set the situation briefly",
                "Action (50%): What you did, with specifics",
                "Result (30%): Quantifiable outcomes",
                "Bridge (10%): Connect to this role",
            ]
        elif style == ResponseStyle.TECHNICAL:
            structure = [
                "Problem (15%): Define the technical challenge",
                "Analysis (25%): Trade-offs considered",
                "Solution (35%): Implementation details",
                "Outcome (20%): Results and learnings",
                "Relevance (5%): How it applies here",
            ]
        elif style == ResponseStyle.COMMERCIAL:
            structure = [
                "Need (20%): Acknowledge their business need",
                "Proof (50%): Your relevant experience",
                "Value (25%): What you'd bring to this role",
                "Close (5%): Forward-looking statement",
            ]
        else:  # MIXED
            structure = [
                "Opening (10%): Direct answer to main question",
                "Evidence (40%): Support from your experience",
                "Detail (30%): Address secondary points",
                "Close (20%): Connect to role and company",
            ]
        
        # Adjust for sub-questions
        if sub_questions and len(sub_questions) > 1:
            must_answer = [sq for sq in sub_questions if sq.priority == Priority.MUST_ANSWER]
            if must_answer:
                structure.insert(0, f"Priority: Address {len(must_answer)} must-answer points first")
        
        return structure


# Unit tests
if __name__ == "__main__":
    import asyncio
    
    async def test():
        analyzer = QuestionAnalyzer(use_llm=False)
        
        # Test simple question
        analysis = await analyzer.analyze("Tell me about your experience")
        print(f"Type: {analysis.primary_type}")
        print(f"Intent: {analysis.underlying_intent}")
        
        # Test compound question
        compound = "Estamos buscando una persona que ocupe el rol de CTO en la compañía, la cual debe poder dar estructura no solo a nivel tecnológico, sino a nivel operativo alineado con las necesidades internas y de nuestros clientes, que permita traer resultados medibles. Para eso nos gustaría saber tu experiencia, si has tenido oportunidad de crear equipos desde cero, cuéntanos más sobre ti."
        analysis = await analyzer.analyze(compound)
        print(f"\nCompound: {analysis.is_compound}")
        print(f"Sub-questions: {len(analysis.sub_questions)}")
        for sq in analysis.sub_questions:
            print(f"  - [{sq.priority}] {sq.text[:50]}...")
    
    asyncio.run(test())
