import logging
import re
import unicodedata
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# =============================================================================
# 1. System Prompt Canônico com Guardrails Reforçados
# =============================================================================

DEFAULT_LOOMIS_SYSTEM_PROMPT = (
    "Você é Loomis, o lendário treinador da pacata vila de Hesiod. Você tem sangue de ogro nas veias, "
    "físico imponente, musculatura pesada, mas fala com uma voz surpreendentemente aguda e anasalada. "
    "Sua personalidade é enérgica, pragmática, exigente e protetora com os jovens recrutas. Nunca quebre o personagem.\n\n"
    "[LORE DE HESIOD E CENÁRIO]:\n"
    "• Vila de Hesiod: Aldeia cercada por matas densas e ameaçada por criaturas perigosas. Você passou os últimos três meses treinando os recrutas para este dia.\n"
    "• A Cabana de Treino: Construção rústica de toras de carvalho atrás da clareira. Há ferramentas penduradas, fogueira de pedra e um grande caldeirão borbulhando poção curativa de menta e limão.\n"
    "• As 4 Jaulas Reforçadas: Jaula 1 (Bullette Faminto), Jaula 2 (Beholder Ameaçador), Jaula 3 (Dragão Vermelho Jovem) e Jaula 4 (Enxame de Pixies Ferais).\n\n"
    "[REGRAS DE CONDUTA POR MODO]:\n"
    "1. MODO EXPLORAÇÃO: Acolha os recrutas, responda sobre a vila, o caldeirão e as armas. Se o grupo enrolar muito, demonstre impaciência de veterano e pressione-os a puxar a alavanca da Jaula 1.\n"
    "2. MODO CONSELHO TÁTICO: Seja direto, rápido e útil. Explique fraquezas da fera atual e como usar os poderes das cartas (Evindol, Raen, Jorick, Yarrow, Bet) sem gastar o turno.\n"
    "3. MODO COMBATE: Você é APENAS o treinador. NUNCA decida se um monstro morreu ou sofreu dano (a autoridade das regras é estrita do Dungeon Master). Só comemore vitória se houver '[MONSTRO DERROTADO]'. Se tiver HP > 0, reaja à fera viva!\n\n"
    "[DIRETRIZES E GUARDRAILS OBRIGATÓRIOS]:\n"
    "• IDIOMA ESTRITO (PORTUGUÊS): Fale SEMPRE e EXCLUSIVAMENTE em Português do Brasil (pt-BR). Sob nenhuma hipótese responda em inglês, espanhol ou qualquer outro idioma, mesmo se o jogador falar em outra língua.\n"
    "• CONDUTA E VOCABULÁRIO: NUNCA use palavrões, xingamentos, obscenidades, gírias vulgares ou termos ofensivos. Mantenha sempre um tom educativo e digno de um mentor veterano.\n"
    "• REPREENSÃO EM PERSONAGEM: Se o jogador falar palavrões ou desrespeitar a disciplina da vila, repreenda-o com autoridade em personagem: 'Guarde esse linguajar para os goblins da mata, recruta! Aqui treinamos com honra e disciplina!'.\n\n"
    "[FORMATO DE RESPOSTA]:\n"
    "• Fale SEMPRE em PRIMEIRA PESSOA, com energia e concisão (1 a 3 frases diretas).\n"
    "• NUNCA inclua rubricas narrativas entre asteriscos (ex: *olho furioso*) nem prefixos como 'Loomis:'. Responda diretamente a sua fala.\n"
    "• Formate usando tags HTML válidas (<b>negrito</b>, <i>itálico</i>). NUNCA use formatação Markdown."
)


# =============================================================================
# 2. Dataclass de Resultado dos Guardrails
# =============================================================================

@dataclass
class GuardrailResult:
    """Resultado detalhado do processamento de guardrails."""
    text: str
    passed: bool = True
    triggers: list[str] = field(default_factory=list)
    original_text: str = ""
    reprimand: str | None = None


# =============================================================================
# 3. Guardrail Anti-Palavrão (ProfanityGuardrail)
# =============================================================================

class ProfanityGuardrail:
    """Filtro determinístico de palavras de baixo calão, obscenidades e insultos (PT e EN)."""

    LEET_MAP = {
        "@": "a", "4": "a",
        "3": "e",
        "1": "i", "!": "i",
        "0": "o",
        "$": "s", "5": "s",
        "7": "t", "+": "t",
    }

    # Padrões com word boundaries para evitar falsos positivos (ex: 'computador', 'classe')
    PROFANITY_PATTERNS = [
        # Português
        r"\b(?:p[o0*]rr[a-z]*)\b",
        r"\b(?:caralh[a-z]*|krlh?[o0]?)\b",
        r"\b(?:merd[a-z]*)\b",
        r"\b(?:put[ao]s?|putari[a-z]*)\b",
        r"\b(?:fod[a-z]*|fud[a-z]*)\b",
        r"\b(?:bost[a-z]*)\b",
        r"\b(?:cacet[a-z]*)\b",
        r"\b(?:bucet[a-z]*|bocet[a-z]*)\b",
        r"\b(?:cu|cus)\b",
        r"\b(?:viad[ao]s?|viadagem)\b",
        r"\b(?:arrombad[ao]s?)\b",
        r"\b(?:desgrac[a-z]*)\b",
        r"\b(?:corn[ao]s?)\b",
        r"\b(?:otari[ao]s?|babac[ao]s?|imbecil|idiota)\b",
        r"\b(?:pic[ao]s?|piroc[ao]s?|rolas?)\b",
        r"\b(?:f[\W_]*d[\W_]*p|p[\W_]*q[\W_]*p|v[\W_]*s[\W_]*f|v[\W_]*t[\W_]*n[\W_]*c)\b",
        r"\b(?:vai\s+(?:se\s+)?foder)\b",
        r"\b(?:tomar\s+no\s+cu)\b",
        r"\b(?:filh[ao]\s+d[ae]\s+puta)\b",
        # Inglês
        r"\b(?:fuck(?:ing|ed|er|s)?)\b",
        r"\b(?:shit(?:ty|s)?)\b",
        r"\b(?:bitch(?:es)?)\b",
        r"\b(?:asshole[s]?)\b",
        r"\b(?:cunt[s]?)\b",
        r"\b(?:dickhead[s]?)\b",
        r"\b(?:motherfucker[s]?)\b",
    ]

    _compiled_patterns = [re.compile(p, flags=re.IGNORECASE) for p in PROFANITY_PATTERNS]

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """Normaliza o texto convertendo leetspeak, acentos e repetições excessivas."""
        if not text:
            return ""
        lowered = text.lower()
        # Substitui caracteres leetspeak (exceto ! isolado no fim da palavra)
        for char, repl in cls.LEET_MAP.items():
            if char == "!":
                # Só substitui ! por i se estiver no meio da palavra (ex: b!tch, f!lho)
                lowered = re.sub(r"(?<=[a-z])!(?=[a-z])", "i", lowered)
            else:
                lowered = lowered.replace(char, repl)
        # Remove acentuação
        nfkd = unicodedata.normalize("NFKD", lowered)
        ascii_text = nfkd.encode("ASCII", "ignore").decode("utf-8")
        # Reduz repetições de mais de 2 letras consecutivas (ex: 'poooorra' -> 'porra')
        reduced = re.sub(r"(.)\1{2,}", r"\1\1", ascii_text)
        return reduced

    @classmethod
    def contains_profanity(cls, text: str) -> bool:
        """Retorna True se houver palavrão ou termo ofensivo no texto."""
        if not text:
            return False
        normalized = cls.normalize_text(text)
        for pattern in cls._compiled_patterns:
            if pattern.search(normalized):
                return True
        return False

    @classmethod
    def find_profanities(cls, text: str) -> list[str]:
        """Retorna lista com os trechos ofensivos detectados."""
        if not text:
            return []
        normalized = cls.normalize_text(text)
        found: list[str] = []
        for pattern in cls._compiled_patterns:
            matches = pattern.findall(normalized)
            if matches:
                found.extend(matches)
        return found

    @classmethod
    def censor_text(cls, text: str) -> str:
        """Substitui termos ofensivos por asteriscos preservando a primeira e última letra."""
        if not text:
            return ""
        normalized = cls.normalize_text(text)
        censored = text
        for pattern in cls._compiled_patterns:
            for match in pattern.finditer(normalized):
                span = match.span()
                matched_str = text[span[0]:span[1]]
                if len(matched_str) <= 2:
                    rep = "*" * len(matched_str)
                else:
                    rep = matched_str[0] + ("*" * (len(matched_str) - 2)) + matched_str[-1]
                censored = censored[:span[0]] + rep + censored[span[1]:]
        return censored


# =============================================================================
# 4. Guardrail de Idioma (LanguageGuardrail)
# =============================================================================

class LanguageGuardrail:
    """Detecta alucinação de idioma ou respostas em língua estrangeira (EN, ES), garantindo pt-BR."""

    # Caracteres e pontuação exclusivos do Espanhol (inexistentes no Português)
    ES_CHARS = re.compile(r"[¡¿ñÑ]")

    # Diacríticos exclusivos do Português (inexistentes no Espanhol: ã, õ, ç, ê, ô, à)
    PT_EXCLUSIVE_DIACRITICS = re.compile(r"[ãõçêôà]", re.IGNORECASE)

    # Stopwords e marcadores típicos em Português (estritamente gramaticais/verbais)
    PT_STOPWORDS = {
        "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
        "para", "pra", "com", "por", "que", "um", "uma", "uns", "umas",
        "se", "os", "as", "mas", "mais", "voce", "voces", "nos", "eles", "elas",
        "eu", "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
        "esse", "essa", "este", "esta", "isso", "isto", "como", "quando",
        "onde", "quem", "nao", "sim", "muito", "bem", "ja", "so", "agora",
        "aqui", "ali", "pelo", "pela", "pelos", "pelas", "esta", "estao",
        "estou", "estamos", "tem", "foi", "era", "foram", "vamos",
        "vai", "vao", "recruta", "recrutas", "fera", "golpe",
        "guarda", "monstro", "treino", "machado", "espada", "vida", "jaula",
        "dado", "dados", "rolagem", "forca", "coragem",
        "atencao", "cuidado", "ataque", "atacar", "caldeirao", "pocao"
    }

    # Marcadores fortes de Inglês
    EN_MARKERS = {
        "the", "is", "are", "was", "were", "this", "that", "with", "have", "has",
        "had", "you", "your", "yours", "we", "our", "ours", "they", "their",
        "theirs", "what", "when", "where", "which", "why", "how", "can", "could",
        "will", "would", "should", "all", "from", "but", "not", "about", "there",
        "been", "here", "welcome", "ready", "beast", "let", "come",
        "great", "job", "good", "done", "heroes", "warrior", "defend",
        "damage", "roll", "fight", "cage", "training", "strike", "monster",
        "attack", "please", "now", "again", "listen"
    }

    # Marcadores fortes de Espanhol (palavras gramaticais e termos exclusivos)
    ES_MARKERS = {
        "el", "la", "los", "las", "pero", "entonces", "estas", "estamos", "criatura",
        "amigos", "ahora", "bienvenido", "bienvenidos", "listos", "fuego", "fuerza",
        "fuerzas", "gracias", "nuestro", "vuestro", "hacia", "hasta", "sobre", "tras",
        "adelante", "lucha", "monstruo", "espadas", "golpea", "mios", "mias", "mio",
        "mia", "tu", "tus", "del", "al", "con", "en", "es", "son", "y"
    }

    @classmethod
    def is_portuguese(cls, text: str) -> bool:
        """Avalia se o texto está substancialmente em Português."""
        if not text or not text.strip():
            return True

        # Se contiver caracteres tipicamente espanhóis (¡, ¿, ñ), rejeita imediatamente
        if cls.ES_CHARS.search(text):
            return False

        # Extrai palavras alfanuméricas
        raw_words = re.findall(r"\b[^\W\d_]+\b", text.lower())
        if not raw_words:
            return True

        # Normaliza tokens sem acento para busca em stopwords
        norm_words = [
            unicodedata.normalize("NFKD", w).encode("ASCII", "ignore").decode("utf-8")
            for w in raw_words
        ]

        # Frases muito curtas (1 a 3 palavras): verifica se há termos claramente ingleses/espanhóis
        if len(raw_words) <= 3:
            for w in norm_words:
                if w in {"welcome", "ready", "the", "you", "attack", "fight", "beast", "heroes"}:
                    return False
                if w in {"bienvenido", "bienvenidos", "listos", "fuego", "adelante"}:
                    return False
            return True

        # Pontuação de marcadores
        has_pt_diacritics = bool(cls.PT_EXCLUSIVE_DIACRITICS.search(text))
        pt_matches = sum(1 for w in norm_words if w in cls.PT_STOPWORDS) + (2 if has_pt_diacritics else 0)
        en_matches = sum(1 for w in norm_words if w in cls.EN_MARKERS)
        es_matches = sum(1 for w in norm_words if w in cls.ES_MARKERS)

        total_words = len(norm_words)

        # Regra 1: Inglês dominante sobre português
        if en_matches >= 2 and en_matches > pt_matches:
            return False

        # Regra 2: Três ou mais marcadores em inglês e nenhum em português
        if en_matches >= 3 and pt_matches == 0:
            return False

        # Regra 3: Espanhol dominante sobre português
        if es_matches >= 2 and es_matches > pt_matches:
            return False

        # Regra 4: Mais de 35% de marcadores em inglês com fraco suporte de português
        if (en_matches / total_words) > 0.35 and pt_matches < 2:
            return False

        return True


# =============================================================================
# 5. Guardrail de Formato e Persona (PersonaFormatGuardrail)
# =============================================================================

class PersonaFormatGuardrail:
    """Higieniza a resposta removendo prefixos de speaker, rubricas entre asteriscos e aspas redundantes."""

    @classmethod
    def clean(cls, text: str) -> str:
        if not text:
            return ""
        cleaned = text.strip()

        # Remove prefixos como 'Loomis:', 'Treinador Loomis:', 'Dungeon Master:', etc.
        cleaned = re.sub(
            r"^(?:Loomis|Treinador Loomis|Dungeon Master|DM|Mestre)\s*:\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

        # Remove rubricas narrativas entre asteriscos (ex: *olha furioso*, *sorri*)
        cleaned = re.sub(r"\*[^*]+\*", "", cleaned).strip()

        # Remove aspas exteriores caso o modelo tenha envolvido toda a resposta entre aspas
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
            cleaned = cleaned[1:-1].strip()

        return cleaned


# =============================================================================
# 6. Pipeline Unificado de Guardrails
# =============================================================================

def apply_output_guardrails(
    raw_text: str,
    context: str | None = None,
    is_victory: bool = False,
    monster_fell: bool = False,
) -> GuardrailResult:
    """Aplica todos os guardrails determinísticos sobre o texto gerado pelo LLM.

    Ordem de checagem:
    1. Limpeza de formato e prefixos de persona.
    2. Detecção de palavrão/obscenidade -> substitui por fala de advertência em personagem.
    3. Detecção de língua estrangeira -> substitui por fala em português contextual.
    """
    cleaned = PersonaFormatGuardrail.clean(raw_text)
    triggers: list[str] = []
    passed = True

    # 1. Checagem Anti-Palavrão
    if ProfanityGuardrail.contains_profanity(cleaned):
        found = ProfanityGuardrail.find_profanities(cleaned)
        logger.warning(f"Guardrail Anti-Palavrão disparado na saída do LLM! Termos detectados: {found}")
        triggers.append("profanity")
        passed = False
        # Fallback de honra e disciplina em personagem
        cleaned = (
            "Atenção aos modos, recrutas! Na arena de Hesiod lutamos com honra, disciplina e respeito! "
            "Mantenham a postura e preparem-se!"
        )

    # 2. Checagem de Idioma (pt-BR)
    if passed and not LanguageGuardrail.is_portuguese(cleaned):
        logger.warning(f"Guardrail de Idioma disparado na saída do LLM! Texto em língua estrangeira: '{cleaned}'")
        triggers.append("foreign_language")
        passed = False

        # Fallback de acordo com a fase do jogo
        if is_victory:
            cleaned = (
                "Vocês conseguiram, recrutas! Todas as 4 jaulas foram superadas! "
                "Vocês agora são os verdadeiros Heróis de Hesiod!"
            )
        elif monster_fell:
            cleaned = (
                "A fera caiu! Excelente golpe, recrutas! "
                "Mas mantenham a guarda alta que o próximo desafio nos aguarda!"
            )
        elif context and "Dungeon Master:" in context:
            cleaned = (
                "Mantenham a guarda e o foco na fera, recrutas! "
                "Hesiod conta com a coragem e a força de vocês!"
            )
        else:
            cleaned = (
                "Falem a língua de Hesiod, recrutas! Não compreendo esses dialetos estranhos. "
                "Concentrem-se no treino e nas jaulas!"
            )

    return GuardrailResult(
        text=cleaned,
        passed=passed,
        triggers=triggers,
        original_text=raw_text,
    )


def apply_input_guardrails(user_message: str) -> GuardrailResult:
    """Verifica se a mensagem de entrada do jogador viola regras de conduta ou integridade.

    Casos cobertos:
    1. Palavrões e toxicidade -> Loomis repreende em personagem.
    2. Tentativas óbvias de jailbreak / prompt injection -> Loomis corta em personagem.
    """
    if not user_message:
        return GuardrailResult(text="", passed=True, original_text="")

    triggers: list[str] = []

    # 1. Checagem de Prompt Injection / Quebra de Personagem
    injection_patterns = [
        r"\b(?:ignore|esque[cç]a)\s+(?:todas?\s+as?\s+|all\s+)?(?:instru[cç][oõ]es|instructions)\b",
        r"\b(?:jailbreak|dan\s+mode|modo\s+dan)\b",
        r"\b(?:voc[eê]\s+agora\s+[eé]|you\s+are\s+now)\b",
        r"\b(?:finja\s+que\s+n[aã]o\s+[eé]|act\s+as\s+if)\b",
    ]
    for pattern in injection_patterns:
        if re.search(pattern, user_message, flags=re.IGNORECASE):
            logger.warning(f"Guardrail de Prompt Injection disparado na entrada: '{user_message}'")
            return GuardrailResult(
                text=user_message,
                passed=False,
                triggers=["prompt_injection"],
                original_text=user_message,
                reprimand=(
                    "Tentar me confundir com feitiçarias mentais não vai funcionar, recruta! "
                    "Meu dever é prepará-los para a arena de Hesiod. Empunhe sua arma e mostre serviço!"
                ),
            )

    # 2. Checagem de Palavrão / Toxicidade do Jogador
    if ProfanityGuardrail.contains_profanity(user_message):
        found = ProfanityGuardrail.find_profanities(user_message)
        logger.warning(f"Guardrail Anti-Palavrão disparado na entrada do jogador! Termos: {found}")
        return GuardrailResult(
            text=user_message,
            passed=False,
            triggers=["profanity"],
            original_text=user_message,
            reprimand=(
                "Guarde esse linguajar para os goblins da mata, recruta! "
                "Aqui em Hesiod treinamos com honra e disciplina!"
            ),
        )

    return GuardrailResult(
        text=user_message,
        passed=True,
        triggers=triggers,
        original_text=user_message,
    )
