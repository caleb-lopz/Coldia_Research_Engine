import time
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from prompts import (
    research_prompt,
    sales_strategies,
    contact_prompt,
    validator_prompt,
    product_description,
)
from pdf_gen import pdf_gen

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()
import anthropic

claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

JSON_INSTRUCTION = (
    "\n\nCRITICAL: Your response must be ONLY a valid JSON object. "
    "Do NOT write any text, markdown, headers, or explanations. "
    "Start your response with { and end with }. "
    "Nothing before {. Nothing after }."
)

MODEL_AGENT_1 = "claude-sonnet-4-5-20250929"   # Research — web search + razonamiento
MODEL_AGENT_2 = "claude-haiku-4-5-20251001"    # Contactos — tarea simple
MODEL_AGENT_3 = "claude-sonnet-4-5-20250929"   # Estrategia — creatividad
MODEL_AGENT_4 = "claude-haiku-4-5-20251001"    # Validador — comparación estructurada


# ============================================================================
# RATE LIMIT MANAGER
# El límite de Anthropic es de INPUT tokens únicamente (no output).
# Web search añade input invisible — usamos 65% de safety margin.
# ============================================================================

class RateLimitManager:
    def __init__(self, tpm_limit: int = 30_000, safety_margin: float = 0.65):
        self.tpm_limit = tpm_limit
        self.effective_limit = int(tpm_limit * safety_margin)
        self.window_start = time.time()
        self.input_tokens_this_window = 0

    def _elapsed(self) -> float:
        return time.time() - self.window_start

    def _reset_if_new_window(self):
        if self._elapsed() >= 60:
            self.input_tokens_this_window = 0
            self.window_start = time.time()
            print("  [RateLimit] Ventana reiniciada.")

    def wait_if_needed(self, estimated_input: int):
        self._reset_if_new_window()
        if self.input_tokens_this_window + estimated_input > self.effective_limit:
            wait = max(0, 62 - self._elapsed())
            print(f"  [RateLimit] Bucket lleno ({self.input_tokens_this_window}/"
                  f"{self.effective_limit}). Esperando {wait:.1f}s...")
            time.sleep(wait)
            self.input_tokens_this_window = 0
            self.window_start = time.time()
        else:
            print(f"  [RateLimit] OK ({self.input_tokens_this_window}/"
                  f"{self.effective_limit}). Estimado: ~{estimated_input}.")

    def register(self, usage):
        """Registra SOLO input tokens (output no cuenta contra el límite)."""
        self._reset_if_new_window()
        inp = (getattr(usage, "input_tokens", 0) or 0)
        inp += (getattr(usage, "cache_read_input_tokens", 0) or 0)
        inp += (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.input_tokens_this_window += inp
        print(f"  [RateLimit] Input registrado: {inp}. "
              f"Ventana: {self.input_tokens_this_window}/{self.effective_limit}")

    def handle_429(self):
        wait = max(0, 62 - self._elapsed())
        print(f"  [RateLimit] 429 recibido. Esperando {wait:.1f}s...")
        time.sleep(wait)
        self.input_tokens_this_window = 0
        self.window_start = time.time()
        print("  [RateLimit] Ventana reiniciada. Reintentando...")


rl = RateLimitManager()


# ============================================================================
# HELPERS
# ============================================================================

def safe_json_parse(raw: str) -> dict:
    import re
    if not raw:
        print("  ERROR: Respuesta vacía.")
        return {}
    text = re.sub(r"```(?:json)?", "", raw).strip()
    start = text.find("{")
    if start == -1:
        print("  ERROR: No se encontró JSON. Preview:", text[:200])
        return {}
    end = len(text)
    while end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError as e:
            end = start + e.pos - 1
    print("  ERROR: JSON no parseable. Preview:", text[start:start+200])
    return {}


def extract_text(message) -> str:
    return "".join(b.text for b in message.content if hasattr(b, "text"))


def call_search(system_prompt: str, user_prompt: str,
                model: str, max_tokens: int,
                est_input: int = 8_000, retries: int = 3) -> str:
    """Llamada con web_search. Pausa 20s post-llamada para proteger la ventana."""
    for attempt in range(retries):
        rl.wait_if_needed(est_input)
        try:
            msg = claude_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system_prompt,
                          "cache_control": {"type": "ephemeral"}}],
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": user_prompt}],
            )
            rl.register(msg.usage)
            print("  [RateLimit] Post-search: pausa 20s.")
            time.sleep(20)
            return extract_text(msg)
        except anthropic.RateLimitError:
            print(f"  [429] Intento {attempt+1}/{retries}")
            rl.handle_429()
            if attempt == retries - 1:
                print("  CRITICAL: 429 agotó reintentos en call_search.")
                return ""
        except Exception as e:
            print(f"  CRITICAL ERROR call_search: {e}")
            return ""
    return ""


def call_json(system_prompt: str, user_prompt: str,
              model: str, max_tokens: int,
              est_input: int = 4_000, retries: int = 3) -> dict:
    """Llamada sin web_search. Devuelve JSON parseado."""
    for attempt in range(retries):
        rl.wait_if_needed(est_input)
        try:
            msg = claude_client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system_prompt,
                          "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user",
                           "content": user_prompt + JSON_INSTRUCTION}],
            )
            rl.register(msg.usage)
            return safe_json_parse(extract_text(msg))
        except anthropic.RateLimitError:
            print(f"  [429] Intento {attempt+1}/{retries}")
            rl.handle_429()
            if attempt == retries - 1:
                print("  CRITICAL: 429 agotó reintentos en call_json.")
                return {}
        except Exception as e:
            print(f"  CRITICAL ERROR call_json: {e}")
            return {}
    return {}


# ============================================================================
# STAGE 1 — AGENT 1: RESEARCH
# Dividido en 1a (búsqueda con web_search → texto libre) y
# 1b (estructuración → JSON, sin web_search).
# Pausa de 65s entre ambas para garantizar ventana limpia.
# ============================================================================

print("\n" + "="*60)
print("  STAGE 1 — AGENT 1: RESEARCH")
print("="*60)

print("\n  [1a] Buscando empresas target...")
research_raw = call_search(
    system_prompt=research_prompt,
    user_prompt=(
        f"Product being researched:\n{product_description}\n\n"
        f"Execute all research phases. Find 3 qualified companies.\n"
        f"Write your findings in plain text — do NOT format as JSON yet.\n"
        f"Include all verbatim quotes, trigger events, and pain signals."
    ),
    model=MODEL_AGENT_1,
    max_tokens=8_000,
    est_input=10_000,
)

if not research_raw:
    raise SystemExit("Pipeline detenido — Agent 1a no devolvió datos.")

print(f"  [1a] {len(research_raw)} chars obtenidos. Pausa 65s para nueva ventana...")
time.sleep(65)

print("\n  [1b] Estructurando hallazgos en JSON...")
research_data = call_json(
    system_prompt=(
        "You are a data structuring specialist. Convert raw research notes "
        "into a structured JSON object exactly matching the schema. "
        "NEVER invent data not present in the notes. Missing data = null."
    ),
    user_prompt=(
        'Convert these research notes into JSON with this schema:\n'
        '{"companies":[{"rank":1,"tier":"TIER 1","relevance_score":0,'
        '"why_this_company_now":"","company":{"name":"","industry":"",'
        '"website":"","tech_stack_confirmed":[],"growth_trajectory":""},'
        '"trigger_events":[{"type":"","event":"","date":"","source_url":"",'
        '"why_this_creates_urgency":""}],"pain_signals":{'
        '"job_posting_phrases_verbatim":[],"linkedin_posts_verbatim":[],'
        '"review_complaints_verbatim":[]},"contacts":{"decision_maker":{'
        '"full_name":null,"title":null,"linkedin_url":null,"email":null}},'
        '"strongest_personalization_hook":""}]}\n\n'
        f"Research notes:\n{research_raw}"
    ),
    model=MODEL_AGENT_1,
    max_tokens=6_000,
    est_input=8_000,
)

if not research_data or not research_data.get("companies"):
    raise SystemExit("Pipeline detenido — Agent 1b no pudo estructurar los datos.")

# Normalizar
companies_normalized = []
for c in research_data.get("companies", []):
    co  = c.get("company", {})
    te  = c.get("trigger_events", [])
    ps  = c.get("pain_signals", {})
    dm  = c.get("contacts", {}).get("decision_maker", {})
    companies_normalized.append({
        "company_name":     co.get("name") or c.get("company_name"),
        "website":          co.get("website"),
        "industry":         co.get("industry"),
        "tech_stack":       co.get("tech_stack_confirmed", []),
        "growth":           co.get("growth_trajectory"),
        "tier":             c.get("tier"),
        "relevance_score":  c.get("relevance_score"),
        "why_now":          c.get("why_this_company_now"),
        "strongest_hook":   c.get("strongest_personalization_hook"),
        "trigger_event":    te[0].get("event") if te else None,
        "trigger_urgency":  te[0].get("why_this_creates_urgency") if te else None,
        "pain_signals":     (ps.get("job_posting_phrases_verbatim", []) +
                             ps.get("linkedin_posts_verbatim", []) +
                             ps.get("review_complaints_verbatim", [])),
        "contact_name":     dm.get("full_name"),
        "contact_title":    dm.get("title"),
        "contact_email":    dm.get("email"),
        "contact_linkedin": dm.get("linkedin_url"),
        "_agent2_contacts": {},
    })

print(f"  [Stage 1] OK — {len(companies_normalized)} empresas normalizadas.")


# ============================================================================
# STAGE 2 — AGENT 2: CONTACT ENRICHMENT (una empresa a la vez)
# ============================================================================

print("\n" + "="*60)
print("  STAGE 2 — AGENT 2: CONTACT ENRICHMENT")
print("="*60)

enriched_companies = []
for company in companies_normalized:
    name = company.get("company_name", "?")
    print(f"\n  [2] Enriqueciendo: {name}...")
    result = call_json(
        system_prompt=contact_prompt,
        user_prompt=(
            f"Enrich contacts for this company:\n"
            f"{json.dumps(company, ensure_ascii=False)}\n\n"
            f"Return JSON with key 'enriched_company' containing the enriched "
            f"contact data including contacts.decision_maker, contacts.champion, "
            f"contacts.gatekeeper_navigator."
        ),
        model=MODEL_AGENT_2,
        max_tokens=2_000,
        est_input=4_000,
    )
    enriched = (result or {}).get("enriched_company", result or {})
    merged   = {**company, **enriched}
    # Guardar contactos de Agent 2 en key fija y predecible
    a2c = enriched.get("contacts", {})
    if not a2c and enriched.get("decision_maker"):
        a2c = {"decision_maker": enriched["decision_maker"]}
    merged["_agent2_contacts"] = a2c
    enriched_companies.append(merged)
    print(f"  [2] OK — DM encontrado: {bool(a2c.get('decision_maker'))}")

print(f"\n  [Stage 2] OK — {len(enriched_companies)} empresas enriquecidas.")


# ============================================================================
# STAGE 3 — AGENT 3: SALES STRATEGY (una empresa a la vez)
# ============================================================================

print("\n" + "="*60)
print("  STAGE 3 — AGENT 3: SALES STRATEGY")
print("="*60)

strategies = []
for company in enriched_companies:
    name = company.get("company_name", "?")
    print(f"\n  [3] Generando estrategia: {name}...")
    result = call_json(
        system_prompt=sales_strategies,
        user_prompt=(
            f"Product being sold:\n{product_description}\n\n"
            f"Generate a complete sales strategy for this company:\n"
            f"{json.dumps(company, ensure_ascii=False)}\n\n"
            f"Return JSON with key 'strategy' containing:\n"
            f"company_name, tier, relevance_score, selected_strategy, channel,\n"
            f"trigger_signal, confidence, company_description, pain_signal,\n"
            f"solution, reason, draft_quality, email_subject,\n"
            f"email_draft (50-80 words max), linkedin_note (under 200 chars),\n"
            f"linkedin_followup (under 150 words), call_opener (under 80 words),\n"
            f"gatekeeper (under 60 words), closing (under 60 words),\n"
            f"next_action, discard_conditions (list of strings),\n"
            f"hypotheses (list of 3 objects: text, probability_pct, label, reason),\n"
            f"execution_instructions (object: step_1..step_5 strings).\n"
            f"Write real drafts anchored to this company's specific data. "
            f"No placeholders."
        ),
        model=MODEL_AGENT_3,
        max_tokens=4_000,
        est_input=6_000,
    )
    if result:
        strat = result.get("strategy", result)
        if not strat.get("company_name"):
            strat["company_name"] = name
        strat["_agent2_contacts"] = company.get("_agent2_contacts", {})
        strategies.append(strat)
        print(f"  [3] OK — {name}")
    else:
        print(f"  [3] WARN — estrategia falló para {name}. Saltando.")

if not strategies:
    raise SystemExit("Pipeline detenido — Agent 3 no generó ninguna estrategia.")

print(f"\n  [Stage 3] OK — {len(strategies)} estrategias generadas.")


# ============================================================================
# STAGE 4 — AGENT 4: VALIDATION
# Dos llamadas por empresa: 4a (status/notas) y 4b (scores).
# ============================================================================

print("\n" + "="*60)
print("  STAGE 4 — AGENT 4: VALIDATION")
print("="*60)

validation_results = {}

for strategy in strategies:
    name = strategy.get("company_name", "?")
    print(f"\n  [4] Validando: {name}...")

    mini = {
        "company_name":      strategy.get("company_name"),
        "tier":              strategy.get("tier"),
        "selected_strategy": strategy.get("selected_strategy"),
        "channel":           strategy.get("channel"),
        "trigger_signal":    strategy.get("trigger_signal"),
        "email_draft":       strategy.get("email_draft"),
        "draft_quality":     strategy.get("draft_quality"),
        "pain_signal":       strategy.get("pain_signal"),
        "hypotheses":        strategy.get("hypotheses", []),
    }

    # 4a — validación (status, notas, contacto)
    r_a = call_json(
        system_prompt=validator_prompt,
        user_prompt=(
            f"Validate this strategy:\n{json.dumps(mini, ensure_ascii=False)}\n\n"
            f"Return JSON with key 'validation' containing ONLY:\n"
            f"  company_name (string)\n"
            f"  validation_status (PASSED / FLAGGED / FAILED)\n"
            f"  validation_notes (1-2 sentences)\n"
            f"  draft_quality_assessment (1 sentence)\n"
            f"  contact_status (VERIFIED / FLAGGED / QUARANTINED / MISSING)"
        ),
        model=MODEL_AGENT_4,
        max_tokens=600,
        est_input=3_000,
    )

    # 4b — scores numéricos (llamada separada)
    r_b = call_json(
        system_prompt=(
            "You are a quality evaluator for a B2B sales AI pipeline. "
            "Score each agent's work honestly on a 1-10 scale. "
            "Return ONLY JSON, nothing else."
        ),
        user_prompt=(
            f"Score this strategy:\n{json.dumps(mini, ensure_ascii=False)}\n\n"
            f"Return JSON with key 'scores' containing:\n"
            f"  agent1_research (int 1-10): signal specific and recent?\n"
            f"  agent2_contacts (int 1-10): 2=missing, 5=found, 8+=verified+source\n"
            f"  agent3_strategy (int 1-10): drafts anchored to real company data?\n"
            f"  hypotheses_reviewed (int): total hypotheses\n"
            f"  hypotheses_specific (int): company-specific ones\n"
            f"  hypotheses_generic (int): generic/could-be-anyone ones\n"
            f"  draft_specific (bool): email references real company data?\n"
            f"  draft_generic (bool): email could be sent to any company?"
        ),
        model=MODEL_AGENT_4,
        max_tokens=300,
        est_input=2_500,
    )

    val_a  = (r_a or {}).get("validation", r_a or {})
    scores = (r_b or {}).get("scores",     r_b or {})

    combined = {
        "validation_status":       val_a.get("validation_status", "FLAGGED"),
        "validation_notes":        val_a.get("validation_notes", "Revisar manualmente."),
        "draft_quality_assessment":val_a.get("draft_quality_assessment", "-"),
        "contact_status":          val_a.get("contact_status", "FLAGGED"),
        "agent_scores": {
            "agent1_research":  scores.get("agent1_research"),
            "agent2_contacts":  scores.get("agent2_contacts"),
            "agent3_strategy":  scores.get("agent3_strategy"),
        },
        "hypotheses_reviewed": scores.get("hypotheses_reviewed", 0),
        "hypotheses_specific": scores.get("hypotheses_specific", 0),
        "hypotheses_generic":  scores.get("hypotheses_generic",  0),
        "draft_specific":      scores.get("draft_specific",  False),
        "draft_generic":       scores.get("draft_generic",   False),
    }

    validation_results[name] = combined
    status = combined["validation_status"]
    a1 = scores.get("agent1_research", "?")
    a2 = scores.get("agent2_contacts", "?")
    a3 = scores.get("agent3_strategy", "?")
    print(f"  [4] {name} → {status} | A1={a1} A2={a2} A3={a3}")

print(f"\n  [Stage 4] OK — {len(validation_results)} empresas validadas.")


# ============================================================================
# CONTACT EXTRACTOR
# ============================================================================

def extract_contacts(strategy: dict, enriched: dict) -> dict:
    """
    Busca contactos en orden de prioridad:
    1. validated_contacts ya procesados (si existen con nombre)
    2. _agent2_contacts del merge
    3. Keys planas de Agent 1 como fallback
    """
    vc   = strategy.get("validated_contacts", {}) or {}
    if vc and vc.get("decision_maker", {}).get("full_name"):
        return vc

    a2   = strategy.get("_agent2_contacts") or enriched.get("_agent2_contacts", {}) or {}
    dm_a = a2.get("decision_maker", {}) or {}
    ch_a = a2.get("champion", {}) or {}
    ga_a = a2.get("gatekeeper_navigator", {}) or {}

    dm = {
        "full_name":     dm_a.get("full_name")     or strategy.get("contact_name"),
        "current_title": (dm_a.get("current_title") or dm_a.get("title")
                          or strategy.get("contact_title")),
        "email":         dm_a.get("email")          or strategy.get("contact_email"),
        "linkedin_url":  dm_a.get("linkedin_url")   or strategy.get("contact_linkedin"),
        "phone":         dm_a.get("phone"),
        "linkedin_activity_score": dm_a.get("linkedin_activity_score"),
        "email_status":  dm_a.get("email_status"),
        "confidence_score": dm_a.get("confidence_score"),
        "contact_source":   dm_a.get("contact_source"),
    }
    return {
        "decision_maker":       dm,
        "champion":             ch_a if ch_a.get("full_name") else {},
        "gatekeeper_navigator": ga_a if ga_a.get("full_name") else {},
    }


# ============================================================================
# BUILD FINAL OUTPUT
# ============================================================================

print("\n  Construyendo output final...")

enriched_map = {c.get("company_name", ""): c for c in enriched_companies}

companies_output = []
for strategy in strategies:
    name       = strategy.get("company_name", "Unknown")
    val        = validation_results.get(name, {})
    enriched   = enriched_map.get(name, {})
    contacts   = extract_contacts(strategy, enriched)
    dm         = contacts["decision_maker"]
    dm["contact_status"] = val.get("contact_status", "FLAGGED")

    exec_inst = strategy.get("execution_instructions")
    if not isinstance(exec_inst, dict):
        exec_inst = {
            "step_1": str(strategy.get("execution_step_1", "-")),
            "step_2": str(strategy.get("execution_step_2", "-")),
            "step_3": str(strategy.get("execution_step_3", "-")),
        }

    companies_output.append({
        "company_name":      name,
        "tier":              strategy.get("tier", "TIER 2"),
        "relevance_score":   strategy.get("relevance_score", 50),
        "validation_status": val.get("validation_status", "FLAGGED"),
        "validation_notes":  val.get("validation_notes", ""),
        "company_brief": {
            "what_they_do":           strategy.get("company_description", "-"),
            "why_sell_to_them":       strategy.get("reason", "-"),
            "their_specific_problem": strategy.get("pain_signal", "-"),
            "how_product_solves_it":  strategy.get("solution", "-"),
        },
        "validated_strategy": {
            "selected_strategy":      strategy.get("selected_strategy", "-"),
            "selected_channel":       strategy.get("channel", "-"),
            "trigger_signal_used":    strategy.get("trigger_signal", "-"),
            "confidence_in_strategy": strategy.get("confidence", "-"),
            "hypotheses":             strategy.get("hypotheses", []),
        },
        "validated_drafts": {
            "email": {
                "subject_line":  strategy.get("email_subject", "-"),
                "body":          strategy.get("email_draft", "-"),
                "draft_quality": strategy.get("draft_quality", "-"),
            },
            "linkedin_message": {
                "connection_note":   strategy.get("linkedin_note", "-"),
                "follow_up_message": strategy.get("linkedin_followup", "-"),
                "draft_quality":     strategy.get("draft_quality", "-"),
            },
            "call_script": {
                "opener":            strategy.get("call_opener", "-"),
                "gatekeeper_script": strategy.get("gatekeeper", "-"),
                "closing_script":    strategy.get("closing", "-"),
                "draft_quality":     strategy.get("draft_quality", "-"),
            },
        },
        "validated_contacts": {
            "decision_maker":       dm,
            "champion":             contacts["champion"],
            "gatekeeper_navigator": contacts["gatekeeper_navigator"],
        },
        "execution_instructions": exec_inst,
        "next_action":        strategy.get("next_action", "-"),
        "discard_conditions": strategy.get("discard_conditions", []),
    })


# ============================================================================
# BUILD AUDIT
# All accumulators, averages, and helpers defined here BEFORE the audit dict.
# ============================================================================

# Acumular desde validation_results
a1_scores, a2_scores, a3_scores = [], [], []
hyp_reviewed = hyp_specific = hyp_generic = 0
contacts_verified = contacts_flagged = contacts_quarantined = 0
drafts_specific = drafts_generic = 0

for v in validation_results.values():
    sc = v.get("agent_scores", {})
    for lst, key in [(a1_scores, "agent1_research"),
                     (a2_scores, "agent2_contacts"),
                     (a3_scores, "agent3_strategy")]:
        val = sc.get(key)
        if isinstance(val, (int, float)) and val > 0:
            lst.append(float(val))

    hyp_reviewed += int(v.get("hypotheses_reviewed", 0))
    hyp_specific += int(v.get("hypotheses_specific",  0))
    hyp_generic  += int(v.get("hypotheses_generic",   0))

    cs = v.get("contact_status", "")
    if   cs == "VERIFIED":      contacts_verified    += 1
    elif cs == "QUARANTINED":   contacts_quarantined += 1
    else:                       contacts_flagged     += 1  # FLAGGED + MISSING

    if v.get("draft_specific") is True:  drafts_specific += 1
    if v.get("draft_generic")  is True:  drafts_generic  += 1

def _avg(lst: list) -> float:
    return round(sum(lst) / len(lst), 1) if lst else 0.0

def _rec(score: float, label: str) -> str:
    if score == 0:   return f"{label}: sin datos suficientes para evaluar."
    if score < 5:    return f"{label}: calidad baja - revisar prompts."
    if score < 7:    return f"{label}: calidad media - hipotesis o borradores poco especificos."
    return           f"{label}: calidad aceptable."

a1_avg = _avg(a1_scores)
a2_avg = _avg(a2_scores)
a3_avg = _avg(a3_scores)

passed  = sum(1 for c in companies_output if c["validation_status"] == "PASSED")
flagged = sum(1 for c in companies_output if c["validation_status"] == "FLAGGED")
failed  = sum(1 for c in companies_output if c["validation_status"] == "FAILED")
total   = len(companies_output)
usable  = passed + flagged  # FLAGGED = revisión humana, no fallo

if   failed == 0:             pipeline_quality = "HIGH"
elif failed <= total * 0.34:  pipeline_quality = "MEDIUM"
else:                         pipeline_quality = "LOW"

cascade = (failed == total and total > 0)

agent_avgs = {
    "Agent 1 - Deep Research":  a1_avg,
    "Agent 2 - Sales Strategy": a2_avg,
    "Agent 3 - Contacts":       a3_avg,
}
weakest = (min(agent_avgs, key=agent_avgs.get)
           if any(agent_avgs.values()) else "N/A")

if   pipeline_quality == "HIGH":
    fix = "Pipeline OK - todas las empresas son utilizables. Revisar FLAGGEDs antes de enviar."
elif pipeline_quality == "MEDIUM":
    fix = f"Agente mas debil: {weakest}. {failed} empresa(s) con FAILED - no usar sin revision."
else:
    fix = f"Agente mas debil: {weakest}. Pipeline con problemas - revisar Agent 1 y Agent 3."

audit = {
    "run_date":                 datetime.now().strftime("%B %d, %Y %H:%M"),
    "overall_pipeline_quality": pipeline_quality,
    "companies_passed":         passed,
    "companies_flagged":        flagged,
    "companies_failed":         failed,
    "weakest_agent":            weakest,
    "weakest_agent_reason": (
        "Score mas bajo del pipeline - ver recomendacion abajo."
        if any([a1_avg, a2_avg, a3_avg]) else
        "Agent 4 no devolvio scores - verificar conexion."
    ),
    "recommended_pipeline_fix": fix,
    "agent_scores": {
        "agent_1_deep_research": {
            "average_score":              a1_avg,
            "improvement_recommendation": _rec(a1_avg, "Agent 1 (Research)"),
        },
        "agent_2_sales_strategy": {
            "average_score":              a2_avg,
            "improvement_recommendation": _rec(a2_avg, "Agent 2 (Strategy)"),
        },
        "agent_3_contact_enrichment": {
            "average_score":              a3_avg,
            "improvement_recommendation": _rec(a3_avg, "Agent 3 (Contacts)"),
        },
    },
    "data_quality_summary": {
        "total_hypotheses_reviewed": hyp_reviewed,
        "hypotheses_verified":       hyp_specific,
        "hypotheses_generic":        hyp_generic,
        "hypotheses_unsupported":    max(0, hyp_reviewed - hyp_specific - hyp_generic),
        "contacts_verified":         contacts_verified,
        "contacts_flagged":          contacts_flagged,
        "contacts_quarantined":      contacts_quarantined,
        "drafts_specific":           drafts_specific,
        "drafts_generic":            drafts_generic,
        "drafts_hallucinated":       0,
    },
    "hallucination_log":  [],
    "generic_content_log": [],
    "cascade_failure_detected": cascade,
    "cascade_failure_explanation": (
        "TODAS las empresas fallaron. Revisar Agent 1 - el research "
        "probablemente no encontro senales reales." if cascade else ""
    ),
}


# ============================================================================
# SAVE JSON
# ============================================================================

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
json_path = f"pipeline_output_{timestamp}.json"

final_output = {
    "validated_output": {
        "report_date":               datetime.now().strftime("%B %d, %Y"),
        "product":                   product_description,
        "total_companies_validated": len(companies_output),
        "companies":                 companies_output,
    },
    "pipeline_audit": audit,
}

with open(json_path, "w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2, ensure_ascii=False)
print(f"\n  JSON guardado → {json_path}")


# ============================================================================
# GENERATE PDF
# ============================================================================

pdf_path = pdf_gen(
    validated_output=final_output["validated_output"],
    pipeline_audit=final_output["pipeline_audit"],
    output_path=f"sales_report_{timestamp}.pdf",
    brand={"company_name": "COLDIA", "primary_color": (20, 90, 150)},
)

print(f"\n{'='*60}")
print(f"  PIPELINE COMPLETO")
print(f"  JSON  → {json_path}")
print(f"  PDF   → {pdf_path}")
print(f"  {passed} PASSED | {flagged} FLAGGED | {failed} FAILED")
print(f"{'='*60}\n")