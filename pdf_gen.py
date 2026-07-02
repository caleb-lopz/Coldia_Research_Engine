# pdf_gen.py
from fpdf import FPDF
from datetime import datetime

# ============================================================================
# BRAND DEFAULTS
# ============================================================================

BRAND = {
    "company_name":  "Tu Empresa",
    "report_title":  "Sales Intelligence Report",
    "primary_color": (15,  76, 129),
    "accent_color":  (0,  168, 107),
    "warning_color": (220, 100,  30),
    "danger_color":  (180,  30,  30),
    "light_bg":      (245, 247, 250),
    "text_dark":     (30,   30,  40),
    "text_muted":    (100, 110, 125),
}

TIER_COLORS = {
    "TIER 1": (0,  168, 107),
    "TIER 2": (220, 140,  30),
    "TIER 3": (120, 120, 130),
    "FAILED": (180,  30,  30),
}

# A4 usable width with 15mm margins each side = 180mm
PAGE_W   = 180
MARGIN_L = 15


# ============================================================================
# INTERNAL RENDERER CLASS
# ============================================================================

class _SalesReportPDF(FPDF):

    def __init__(self, brand: dict):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.brand = brand
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(left=MARGIN_L, top=15, right=MARGIN_L)

    # ──────────────────────────────────────────
    # UTILITIES
    # ──────────────────────────────────────────

    def _clean(self, text, max_chars: int = 0) -> str:
        """Sanitize text for latin-1 fonts. Optionally truncate."""
        if text is None:
            return "-"
        s = (
            str(text)
            .replace("\u2014", "-").replace("\u2013", "-")
            .replace("\u2018", "'").replace("\u2019", "'")
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2026", "...").replace("\u2022", "-")
            .replace("\u25cf", "-").replace("\u27a1", "->")
            .replace("\u2192", "->").replace("\u26a0", "!")
            .replace("\u00e9", "e").replace("\u00f3", "o")
            .replace("\u00ed", "i").replace("\u00fa", "u")
            .replace("\u00e1", "a").replace("\u00f1", "n")
            .replace("\u00fc", "u").replace("\u00f6", "o")
            .replace("\u00e4", "a").replace("\u00e0", "a")
            .replace("\u00ec", "i").replace("\u00f2", "o")
            .replace("\u00e8", "e").replace("\u00ea", "e")
        )
        if max_chars and len(s) > max_chars:
            s = s[:max_chars - 3] + "..."
        return s

    def _wrap(self, text, max_chars: int = 90) -> str:
        """Hard-wrap long lines so they don't overflow the page width."""
        if not text:
            return "-"
        s = self._clean(text)
        words = s.split()
        lines, line = [], []
        count = 0
        for w in words:
            if count + len(w) + 1 > max_chars and line:
                lines.append(" ".join(line))
                line, count = [w], len(w)
            else:
                line.append(w)
                count += len(w) + 1
        if line:
            lines.append(" ".join(line))
        return "\n".join(lines)

    # ──────────────────────────────────────────
    # AUTO HEADER / FOOTER
    # ──────────────────────────────────────────

    def header(self):
        self.set_fill_color(*self.brand["primary_color"])
        self.rect(0, 0, 210, 8, style="F")
        self.set_y(10)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["primary_color"])
        self.cell(0, 5, self._clean(self.brand["company_name"]).upper(), align="L")
        self.set_y(10)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*self.brand["text_muted"])
        self.cell(0, 5, f"Page {self.page_no()}", align="R")
        self.ln(6)

    def footer(self):
        self.set_y(-12)
        self.set_fill_color(*self.brand["primary_color"])
        self.rect(0, 285, 210, 12, style="F")
        self.set_font("Helvetica", "", 7)
        self.set_text_color(255, 255, 255)
        self.cell(
            0, 8,
            self._clean(
                f"{self.brand['report_title']} - Confidential - "
                f"{datetime.now().strftime('%B %d, %Y')}"
            ),
            align="C",
        )

    # ──────────────────────────────────────────
    # REUSABLE COMPONENTS
    # ──────────────────────────────────────────

    def _section_label(self, text: str):
        """Bold colored section header with underline."""
        self.ln(3)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["primary_color"])
        self.cell(0, 5, self._clean(text).upper())
        self.ln(5)
        y = self.get_y() - 1
        self.set_draw_color(*self.brand["primary_color"])
        self.line(MARGIN_L, y, 195, y)
        self.ln(2)

    def _body_text(self, text, size: int = 9):
        self.set_font("Helvetica", "", size)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(PAGE_W, 5, self._wrap(text, 95))
        self.ln(2)

    def _kv_row(self, key: str, value, key_w: int = 42):
        """Key: Value row. Value wraps within its column."""
        val_w = PAGE_W - key_w
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["text_muted"])
        # Save cursor
        x0, y0 = self.get_x(), self.get_y()
        self.set_xy(MARGIN_L, y0)
        self.cell(key_w, 5, self._clean(key, 28) + ":")
        # Value in remaining width
        self.set_xy(MARGIN_L + key_w, y0)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(val_w, 5, self._wrap(value, 90))
        self.ln(1)

    def _highlight_box(self, text, color: tuple):
        """Colored left-bar box. Height adapts to text length."""
        if not text or text == "-":
            return
        # Estimate how many lines the text needs
        wrapped = self._wrap(text, 88)
        n_lines = wrapped.count("\n") + 1
        box_h   = max(10, n_lines * 5 + 6)
        y = self.get_y()
        # Check page break manually
        if y + box_h > 272:
            self.add_page()
            y = self.get_y()
        self.set_fill_color(*color)
        self.rect(MARGIN_L, y, 3, box_h, style="F")
        self.set_fill_color(*self.brand["light_bg"])
        self.rect(MARGIN_L + 3, y, PAGE_W - 3, box_h, style="F")
        self.set_xy(MARGIN_L + 6, y + 3)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(PAGE_W - 9, 5, wrapped)
        self.set_y(y + box_h + 3)

    def _draft_box(self, text):
        """
        Monospaced draft box. Background rect drawn FIRST, text on top.
        Uses line_h=5 for accurate height estimate.
        y is recalculated AFTER add_page() so rect never lands on wrong page.
        """
        if not text or text == "-":
            return
        LINE_H  = 5
        wrapped = self._wrap(text, 86)
        n_lines = wrapped.count("\n") + 1
        box_h   = n_lines * LINE_H + 10   # 5 mm padding top + bottom
        # Page break guard — y MUST be read after add_page
        if self.get_y() + box_h + 4 > 272:
            self.add_page()
        y = self.get_y() + 2              # read y here, after possible page break
        # 1. Draw background FIRST
        self.set_fill_color(238, 242, 248)
        self.set_draw_color(*self.brand["text_muted"])
        self.rect(MARGIN_L, y, PAGE_W, box_h, style="FD")
        # 2. Write text ON TOP of background
        self.set_xy(MARGIN_L + 4, y + 5)
        self.set_font("Courier", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(PAGE_W - 8, LINE_H, wrapped)
        self.set_y(y + box_h + 3)

    def _two_col_row(self, left_title, left_text, right_title, right_text):
        col_w = (PAGE_W - 4) // 2   # ~88mm each
        y0 = self.get_y()

        # Left column
        self.set_xy(MARGIN_L, y0)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.brand["primary_color"])
        self.cell(col_w, 5, self._clean(left_title).upper())
        self.set_xy(MARGIN_L, y0 + 5)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(col_w, 5, self._wrap(left_text, 44))
        left_end = self.get_y()

        # Right column
        self.set_xy(MARGIN_L + col_w + 4, y0)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.brand["primary_color"])
        self.cell(col_w, 5, self._clean(right_title).upper())
        self.set_xy(MARGIN_L + col_w + 4, y0 + 5)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(col_w, 5, self._wrap(right_text, 44))
        right_end = self.get_y()

        self.set_y(max(left_end, right_end) + 3)

    def _contact_block(self, role: str, contact: dict):
        if not contact or not contact.get("full_name"):
            return
        status = contact.get("contact_status", "FLAGGED")
        status_color = {
            "VERIFIED":    self.brand["accent_color"],
            "FLAGGED":     self.brand["warning_color"],
            "QUARANTINED": self.brand["danger_color"],
            "MISSING":     self.brand["text_muted"],
        }.get(status, self.brand["text_muted"])

        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["primary_color"])
        self.cell(45, 5, self._clean(role).upper())
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*status_color)
        self.cell(0, 5, f"* {self._clean(status)}")
        self.ln(5)

        fields = [
            ("Name",     contact.get("full_name")),
            ("Title",    contact.get("current_title")),
            ("Email",    contact.get("email")),
            ("LinkedIn", contact.get("linkedin_url")),
            ("Phone",    contact.get("phone")),
            ("Activity", contact.get("linkedin_activity_score")),
            ("Source",   contact.get("contact_source")),
        ]
        for label, val in fields:
            if val:
                self._kv_row(f"  {label}", str(val), key_w=35)
        self.ln(2)

    def _numbered_item(self, num: int, text: str):
        x0, y0 = self.get_x(), self.get_y()
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["primary_color"])
        self.set_xy(MARGIN_L, y0)
        self.cell(7, 5, f"{num}.")
        self.set_xy(MARGIN_L + 7, y0)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.multi_cell(PAGE_W - 7, 5, self._wrap(text, 88))
        self.ln(1)

    def _bullet_item(self, text: str):
        y0 = self.get_y()
        self.set_xy(MARGIN_L, y0)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.cell(5, 5, "-")
        self.set_xy(MARGIN_L + 5, y0)
        self.multi_cell(PAGE_W - 5, 5, self._wrap(text, 88))
        self.ln(1)

    def _score_bar(self, label: str, score: float, note: str = ""):
        """Horizontal score bar for agent scores."""
        bar_color = (
            self.brand["accent_color"]  if score >= 7 else
            self.brand["warning_color"] if score >= 5 else
            self.brand["danger_color"]
        )
        y0 = self.get_y()
        self.set_xy(MARGIN_L, y0)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*self.brand["text_dark"])
        self.cell(65, 6, self._clean(label))
        # Bar background
        bx = MARGIN_L + 65
        self.set_fill_color(220, 225, 232)
        self.rect(bx, y0 + 1, 90, 4, style="F")
        # Bar fill (score/10 * 90mm)
        fill_w = int(score / 10 * 90)
        if fill_w > 0:
            self.set_fill_color(*bar_color)
            self.rect(bx, y0 + 1, fill_w, 4, style="F")
        # Score text
        self.set_xy(bx + 92, y0)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*bar_color)
        self.cell(20, 6, f"{score:.1f}/10")
        self.ln(7)
        if note:
            self.set_x(MARGIN_L + 5)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(*self.brand["text_muted"])
            self.multi_cell(PAGE_W - 5, 4, self._clean(f"-> {note}", 120))
            self.ln(1)

    # ──────────────────────────────────────────
    # STAT BOXES (cover page)
    # ──────────────────────────────────────────

    def _stat_boxes(self, total, tier1, tier2, tier3):
        stats = [
            ("TOTAL",  str(total), self.brand["primary_color"]),
            ("TIER 1", str(tier1), TIER_COLORS["TIER 1"]),
            ("TIER 2", str(tier2), TIER_COLORS["TIER 2"]),
            ("TIER 3", str(tier3), TIER_COLORS["TIER 3"]),
        ]
        box_w, x_start = 42, MARGIN_L
        y = self.get_y()
        for i, (label, value, color) in enumerate(stats):
            x = x_start + i * (box_w + 2)
            self.set_fill_color(*color)
            self.rect(x, y, box_w, 22, style="F")
            self.set_xy(x, y + 3)
            self.set_font("Helvetica", "B", 18)
            self.set_text_color(255, 255, 255)
            self.cell(box_w, 10, value, align="C")
            self.set_xy(x, y + 13)
            self.set_font("Helvetica", "", 7)
            self.cell(box_w, 6, label, align="C")
        self.set_y(y + 26)

    # ──────────────────────────────────────────
    # COVER PAGE
    # ──────────────────────────────────────────

    def cover_page(self, product, total, tier1, tier2, tier3, run_date):
        self.add_page()

        # Hero banner
        self.set_fill_color(*self.brand["primary_color"])
        self.rect(0, 0, 210, 80, style="F")
        self.set_y(25)
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(255, 255, 255)
        self.cell(0, 12, self._clean(self.brand["report_title"]).upper(), align="C")
        self.ln(10)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(180, 210, 240)
        self.cell(0, 6, "Personalized Prospect Intelligence & Sales Strategy", align="C")
        self.ln(28)

        self._stat_boxes(total, tier1, tier2, tier3)
        self.ln(12)

        self._section_label("PRODUCT")
        self._body_text(product)
        self.ln(6)

        self._section_label("GENERATED")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*self.brand["text_muted"])
        self.cell(0, 6, self._clean(run_date))
        self.ln(14)

        # Confidentiality box
        self.set_fill_color(*self.brand["light_bg"])
        self.set_draw_color(*self.brand["primary_color"])
        y = self.get_y()
        self.rect(MARGIN_L, y, PAGE_W, 14, style="FD")
        self.set_xy(MARGIN_L + 4, y + 3)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*self.brand["text_muted"])
        self.multi_cell(PAGE_W - 8, 4,
            "CONFIDENTIAL - This report contains proprietary sales intelligence "
            "for internal use only. Do not distribute outside your organization.")

    # ──────────────────────────────────────────
    # COMPANY PAGE
    # ──────────────────────────────────────────

    def company_page(self, data: dict, section_num: int):
        self.add_page()

        tier   = data.get("tier", "TIER 3")
        name   = self._clean(data.get("company_name", "Unknown"))
        score  = data.get("relevance_score", 0)
        status = self._clean(data.get("validation_status", "FLAGGED"))
        color  = TIER_COLORS.get(tier, TIER_COLORS["TIER 3"])

        # Company banner
        self.set_fill_color(*color)
        self.rect(0, 16, 210, 22, style="F")
        self.set_y(19)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(255, 255, 255)
        self.cell(0, 7, f"{section_num:02d}. {name.upper()}", align="L")
        self.ln(7)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(220, 240, 255)
        self.cell(0, 5, f"{tier}  |  Score: {score}/110  |  Status: {status}", align="L")
        self.ln(12)

        brief = data.get("company_brief", {})
        strat = data.get("validated_strategy", {})
        drafts = data.get("validated_drafts", {})

        # ── Overview
        self._section_label("COMPANY OVERVIEW")
        self._body_text(brief.get("what_they_do"))

        # ── Why now
        self._section_label("WHY CONTACT NOW")
        self._highlight_box(brief.get("why_sell_to_them"), color=self.brand["accent_color"])

        # ── Problem / Solution columns
        self._two_col_row(
            left_title  = "THEIR SPECIFIC PROBLEM",
            left_text   = brief.get("their_specific_problem"),
            right_title = "HOW YOUR PRODUCT SOLVES IT",
            right_text  = brief.get("how_product_solves_it"),
        )

        # ── Recommended strategy
        self._section_label("RECOMMENDED STRATEGY")
        self._kv_row("Strategy",   strat.get("selected_strategy"))
        self._kv_row("Channel",    strat.get("selected_channel"))
        self._kv_row("Signal",     strat.get("trigger_signal_used"))
        self._kv_row("Confidence", strat.get("confidence_in_strategy"))

        # ── Hypotheses
        hypotheses = strat.get("hypotheses", [])
        if hypotheses:
            self._section_label("RANKED HYPOTHESES")
            for i, h in enumerate(hypotheses, 1):
                if isinstance(h, str):
                    self._bullet_item(f"{i}. {h}")
                    continue
                prob   = self._clean(
                    h.get("probability") or
                    (f"{h.get('probability_pct', 0)}%" if h.get("probability_pct") else None) or
                    h.get("label") or "-"
                )
                hyp    = self._clean(h.get("hypothesis") or h.get("text") or "-")
                reason = self._clean(h.get("reasoning") or h.get("reason") or "-")
                prob_color = {
                    "HIGH":   self.brand["accent_color"],
                    "MEDIUM": self.brand["warning_color"],
                    "LOW":    self.brand["text_muted"],
                }.get(prob.upper().split("%")[0].strip(), self.brand["text_muted"])

                y0 = self.get_y()
                self.set_xy(MARGIN_L, y0)
                self.set_font("Helvetica", "B", 8)
                self.set_text_color(*prob_color)
                self.cell(12, 5, f"  {i}.")
                self.set_font("Helvetica", "B", 8)
                self.cell(20, 5, f"[{prob}]")
                self.set_font("Helvetica", "", 8)
                self.set_text_color(*self.brand["text_dark"])
                self.multi_cell(PAGE_W - 32, 5, self._wrap(hyp, 72))
                if reason and reason != "-":
                    self.set_x(MARGIN_L + 32)
                    self.set_font("Helvetica", "I", 7)
                    self.set_text_color(*self.brand["text_muted"])
                    self.multi_cell(PAGE_W - 32, 4, self._wrap(reason, 80))
                self.ln(1)

        # ── EMAIL DRAFT — clean two-part layout
        email = drafts.get("email", {})
        qual  = self._clean(email.get("draft_quality", "-"), 60)
        self._section_label(f"EMAIL DRAFT  [{qual}]")

        # Subject line on its own clearly labeled row
        self._kv_row("Subject", email.get("subject_line"))
        self.ln(1)

        # Body in draft box (monospaced, clearly separated)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.brand["text_muted"])
        self.cell(0, 4, "BODY:")
        self.ln(4)
        self._draft_box(email.get("body"))

        # ── LinkedIn
        li = drafts.get("linkedin_message", {})
        qual_li = self._clean(li.get("draft_quality", "-"), 60)
        self._section_label(f"LINKEDIN MESSAGE  [{qual_li}]")
        self._kv_row("Connection Note", li.get("connection_note"))
        self.ln(1)
        self.set_font("Helvetica", "B", 7)
        self.set_text_color(*self.brand["text_muted"])
        self.cell(0, 4, "FOLLOW-UP MESSAGE:")
        self.ln(4)
        self._draft_box(li.get("follow_up_message"))

        # ── Call script
        call = drafts.get("call_script", {})
        qual_c = self._clean(call.get("draft_quality", "-"), 60)
        self._section_label(f"CALL SCRIPT  [{qual_c}]")
        # Opener — can be long, use body_text styled box
        self._kv_row("Opener (8 sec)", call.get("opener"))
        self._kv_row("Gatekeeper",     call.get("gatekeeper_script"))
        self._kv_row("Closing script", call.get("closing_script"))

        # ── Direct contacts
        contacts = data.get("validated_contacts", {})
        self._section_label("DIRECT CONTACTS")
        self._contact_block("Decision Maker",      contacts.get("decision_maker", {}))
        self._contact_block("Champion",            contacts.get("champion", {}))
        self._contact_block("Gatekeeper Navigator",contacts.get("gatekeeper_navigator", {}))

        # ── Execution instructions
        steps = data.get("execution_instructions", {})
        if steps:
            self._section_label("EXECUTION INSTRUCTIONS")
            for i in range(1, 7):
                step = steps.get(f"step_{i}", "")
                if step and step != "-":
                    self._numbered_item(i, step)

        # ── Next action
        self._section_label("NEXT ACTION")
        self._highlight_box(data.get("next_action"), color=self.brand["primary_color"])

        # ── Discard conditions
        discards = data.get("discard_conditions", [])
        if discards:
            self._section_label("DISCARD CONDITIONS")
            for d in discards:
                self._bullet_item(d)

    # ──────────────────────────────────────────
    # AUDIT PAGE
    # ──────────────────────────────────────────

    def audit_page(self, audit: dict):
        self.add_page()

        # Banner
        self.set_fill_color(*self.brand["primary_color"])
        self.rect(0, 16, 210, 18, style="F")
        self.set_y(20)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(255, 255, 255)
        self.cell(0, 8, "PIPELINE QUALITY AUDIT LOG", align="C")
        self.ln(14)

        # Overall quality badge
        quality = self._clean(audit.get("overall_pipeline_quality", "-"))
        q_color = {
            "HIGH":   self.brand["accent_color"],
            "MEDIUM": self.brand["warning_color"],
            "LOW":    self.brand["danger_color"],
        }.get(quality, self.brand["text_muted"])

        self._section_label("OVERALL PIPELINE QUALITY")
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(*q_color)
        self.cell(0, 10, quality, align="L")
        self.ln(12)

        # Counts row
        passed  = audit.get("companies_passed",  0)
        flagged = audit.get("companies_flagged", 0)
        failed  = audit.get("companies_failed",  0)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.brand["text_dark"])
        self.cell(60, 6, f"PASSED: {passed}")
        self.set_text_color(*self.brand["warning_color"])
        self.cell(60, 6, f"FLAGGED: {flagged}")
        self.set_text_color(*self.brand["danger_color"])
        self.cell(60, 6, f"FAILED: {failed}")
        self.ln(8)

        # Cascade failure alert
        if audit.get("cascade_failure_detected"):
            self._highlight_box(
                "CASCADE FAILURE: " + self._clean(audit.get("cascade_failure_explanation", "")),
                color=self.brand["danger_color"],
            )

        # Weakest agent
        self._section_label("WEAKEST AGENT")
        self._body_text(
            f"{self._clean(audit.get('weakest_agent', '-'))}  -  "
            f"{self._clean(audit.get('weakest_agent_reason', '-'))}"
        )

        # Recommended fix
        self._section_label("RECOMMENDED PIPELINE FIX")
        self._highlight_box(audit.get("recommended_pipeline_fix"), color=self.brand["warning_color"])

        # Agent score bars
        self._section_label("AGENT SCORES")
        scores = audit.get("agent_scores", {})
        agents = [
            ("Agent 1 - Deep Research",  "agent_1_deep_research"),
            ("Agent 2 - Sales Strategy", "agent_2_sales_strategy"),
            ("Agent 3 - Contacts",       "agent_3_contact_enrichment"),
        ]
        for label, key in agents:
            agent_data = scores.get(key, {})
            avg_score  = float(agent_data.get("average_score", 0))
            rec        = agent_data.get("improvement_recommendation", "")
            self._score_bar(label, avg_score, rec)

        # Hallucination log
        hall_log = audit.get("hallucination_log", [])
        if hall_log:
            self._section_label(f"HALLUCINATION LOG ({len(hall_log)} flagged)")
            for entry in hall_log:
                if not isinstance(entry, dict):
                    self._body_text(str(entry))
                    continue
                self.set_font("Helvetica", "B", 7)
                self.set_text_color(*self.brand["danger_color"])
                self.cell(0, 4, self._clean(
                    f"[{entry.get('agent_responsible','?')}] "
                    f"{entry.get('hallucination_type','?')} - "
                    f"{entry.get('company_name','?')}"
                ))
                self.ln(4)
                self.set_x(MARGIN_L + 4)
                self.set_font("Helvetica", "I", 7)
                self.set_text_color(*self.brand["text_muted"])
                self.multi_cell(PAGE_W - 4, 4,
                    self._clean(f"Field: {entry.get('field_affected','-')}  |  "
                                f"Action: {entry.get('action_taken','-')}"))
                self.ln(2)

        # Generic content log
        generic_log = audit.get("generic_content_log", [])
        if generic_log:
            self._section_label(f"GENERIC CONTENT LOG ({len(generic_log)} flagged)")
            for entry in generic_log:
                if not isinstance(entry, dict):
                    self._body_text(str(entry))
                    continue
                self.set_font("Helvetica", "B", 7)
                self.set_text_color(*self.brand["warning_color"])
                self.cell(0, 4, self._clean(
                    f"[{entry.get('agent_responsible','?')}] "
                    f"{entry.get('content_type','?')} - "
                    f"{entry.get('company_name','?')}"
                ))
                self.ln(4)
                self.set_x(MARGIN_L + 4)
                self.set_font("Helvetica", "I", 7)
                self.set_text_color(*self.brand["text_muted"])
                self.multi_cell(PAGE_W - 4, 4,
                    self._clean(entry.get("reason_flagged_as_generic", "-")))
                self.ln(2)

        # Data quality summary
        dqs = audit.get("data_quality_summary", {})
        self._section_label("DATA QUALITY SUMMARY")
        rows = [
            ("Hypotheses reviewed",    dqs.get("total_hypotheses_reviewed", 0)),
            ("Hypotheses verified",    dqs.get("hypotheses_verified",       0)),
            ("Hypotheses generic",     dqs.get("hypotheses_generic",        0)),
            ("Hypotheses unsupported", dqs.get("hypotheses_unsupported",    0)),
            ("Contacts verified",      dqs.get("contacts_verified",         0)),
            ("Contacts flagged",       dqs.get("contacts_flagged",          0)),
            ("Contacts quarantined",   dqs.get("contacts_quarantined",      0)),
            ("Drafts specific",        dqs.get("drafts_specific",           0)),
            ("Drafts generic",         dqs.get("drafts_generic",            0)),
            ("Drafts hallucinated",    dqs.get("drafts_hallucinated",       0)),
        ]
        for label, val in rows:
            self._kv_row(label, str(val))


# ============================================================================
# PUBLIC FUNCTION
# ============================================================================

def pdf_gen(
    validated_output: dict,
    pipeline_audit:   dict,
    output_path:      str  = None,
    brand:            dict = None,
) -> str:
    """
    Generate the Sales Intelligence PDF report.

    Args:
        validated_output : dict with keys: product, report_date,
                           total_companies_validated, companies (list)
        pipeline_audit   : dict with audit metrics
        output_path      : file path (auto-generated if None)
        brand            : dict to override brand defaults
                           (keys: company_name, primary_color, etc.)

    Returns:
        str — path to the generated PDF
    """
    active_brand = {**BRAND, **(brand or {})}
    pdf = _SalesReportPDF(brand=active_brand)

    # ── Normalize validated_output ─────────────────────────────────────────
    if not isinstance(validated_output, dict):
        validated_output = {
            "companies": [], "product": "",
            "report_date": datetime.now().strftime("%B %d, %Y"),
            "total_companies_validated": 0,
        }

    companies = validated_output.get("companies", [])

    # Guard: if companies are flat strategy dicts (no company_brief key),
    # build the structure from what's available.
    if companies and isinstance(companies[0], dict) and "company_brief" not in companies[0]:
        def _minimal_build(s: dict) -> dict:
            return {
                "company_name":      s.get("company_name", "Unknown"),
                "tier":              s.get("tier", "TIER 2"),
                "relevance_score":   s.get("relevance_score", 50),
                "validation_status": s.get("validation_status", "FLAGGED"),
                "validation_notes":  s.get("validation_notes", ""),
                "company_brief": {
                    "what_they_do":           s.get("company_description", "-"),
                    "why_sell_to_them":       s.get("reason", "-"),
                    "their_specific_problem": s.get("pain_signal", "-"),
                    "how_product_solves_it":  s.get("solution", "-"),
                },
                "validated_strategy": {
                    "selected_strategy":      s.get("selected_strategy", "-"),
                    "selected_channel":       s.get("channel", "-"),
                    "trigger_signal_used":    s.get("trigger_signal", "-"),
                    "confidence_in_strategy": s.get("confidence", "-"),
                    "hypotheses":             s.get("hypotheses", []),
                },
                "validated_drafts": {
                    "email": {
                        "subject_line":  s.get("email_subject", "-"),
                        "body":          s.get("email_draft", "-"),
                        "draft_quality": s.get("draft_quality", "-"),
                    },
                    "linkedin_message": {
                        "connection_note":   s.get("linkedin_note", "-"),
                        "follow_up_message": s.get("linkedin_followup", "-"),
                        "draft_quality":     s.get("draft_quality", "-"),
                    },
                    "call_script": {
                        "opener":            s.get("call_opener", "-"),
                        "gatekeeper_script": s.get("gatekeeper", "-"),
                        "closing_script":    s.get("closing", "-"),
                        "draft_quality":     s.get("draft_quality", "-"),
                    },
                },
                "validated_contacts": s.get("validated_contacts", {
                    "decision_maker": {
                        "full_name":     s.get("contact_name"),
                        "current_title": s.get("contact_title"),
                        "email":         s.get("contact_email"),
                        "linkedin_url":  s.get("contact_linkedin"),
                    },
                    "champion": {},
                    "gatekeeper_navigator": {},
                }),
                "execution_instructions": s.get("execution_instructions", {}),
                "next_action":            s.get("next_action", "-"),
                "discard_conditions":     s.get("discard_conditions", []),
            }
        companies = [_minimal_build(c) for c in companies]
        validated_output["companies"] = companies

    if not isinstance(pipeline_audit, dict):
        pipeline_audit = {}

    # ── Tier counts ────────────────────────────────────────────────────────
    tier_counts = {"TIER 1": 0, "TIER 2": 0, "TIER 3": 0}
    for c in companies:
        t = c.get("tier", "TIER 3")
        if t in tier_counts:
            tier_counts[t] += 1

    # ── Render pages ───────────────────────────────────────────────────────
    pdf.cover_page(
        product  = validated_output.get("product", ""),
        total    = validated_output.get("total_companies_validated", len(companies)),
        tier1    = tier_counts["TIER 1"],
        tier2    = tier_counts["TIER 2"],
        tier3    = tier_counts["TIER 3"],
        run_date = validated_output.get("report_date",
                       datetime.now().strftime("%B %d, %Y")),
    )

    for i, company in enumerate(companies, start=1):
        pdf.company_page(company, section_num=i)

    pdf.audit_page(pipeline_audit)

    # ── Save ───────────────────────────────────────────────────────────────
    if not output_path:
        output_path = f"sales_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    pdf.output(output_path)
    print(f"PDF saved -> {output_path}")
    return output_path