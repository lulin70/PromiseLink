"""F-50: NLU Intent Classifier — two-stage intent classification for voice queries.

Strategy:
  1. Rule-based keyword matching (fast, <5ms)
  2. LLM classification fallback (slower, ~200-500ms)

PRD v4.4 F-50 + Algorithm Design §12
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any

from eventlink.core.logging import get_logger
from eventlink.services.llm_client import LLMClient

logger = get_logger("eventlink.nlu")


# ── Enum ──


class VoiceIntent(str, Enum):
    """9 voice intent categories for F-50 NLU."""

    SCHEDULE_QUERY = "schedule_query"
    SCHEDULE_RANGE = "schedule_range"
    PROMISE_TRACKER = "promise_tracker"
    RELATIONSHIP_STATUS = "relationship_status"
    ACTION_SUGGESTION = "action_suggestion"
    TODO_CREATE = "todo_create"
    UNCLEAR = "unclear"
    CHITCHAT = "chitchat"
    EXIT = "exit"


# ── Result ──


@dataclass
class NLUResult:
    """Result of NLU intent classification."""

    intent: VoiceIntent
    confidence: float
    slots: dict[str, Any]
    evidence: str
    method: str  # "rule" | "llm"


# ── Classifier ──


class NLUIntentClassifier:
    """Two-stage NLU intent classifier for voice queries.

    Stage 1: Rule-based matching on keywords (fast, <5ms)
    Stage 2: LLM classification fallback (slower, ~200-500ms)
    """

    RULE_CONFIDENCE_THRESHOLD = 0.85

    def __init__(self, llm_client: LLMClient) -> None:
        self.llm = llm_client

    async def classify(self, query_text: str) -> NLUResult:
        """Classify user's voice query into intent + slots.

        Args:
            query_text: ASR-transcribed text from user's voice input.

        Returns:
            NLUResult with intent, confidence, slots, and evidence.
        """
        if not query_text or not query_text.strip():
            logger.warning("classify_empty_query")
            return NLUResult(
                intent=VoiceIntent.UNCLEAR,
                confidence=0.0,
                slots={},
                evidence="Empty query text",
                method="rule",
            )

        logger.info("nlu_classify_started", query_text=query_text[:100])

        # Step 1: Try rule-based classification
        rule_result = self._rule_classify(query_text)
        if rule_result is not None and rule_result.confidence >= self.RULE_CONFIDENCE_THRESHOLD:
            logger.info(
                "nlu_rule_hit",
                intent=rule_result.intent.value,
                confidence=rule_result.confidence,
                method="rule",
            )
            return rule_result

        # Step 2: Fall back to LLM classification
        llm_result = await self._llm_classify(query_text)
        logger.info(
            "nlu_llm_fallback",
            intent=llm_result.intent.value,
            confidence=llm_result.confidence,
            method="llm",
        )
        return llm_result

    def _rule_classify(self, query_text: str) -> NLUResult | None:
        """Stage 1: Rule-based keyword matching.

        Order matters: more specific intents are checked first to avoid
        false positives from general keywords like '明天' matching before
        specific patterns like '提醒我'.

        Returns None if no rule matches with sufficient confidence.
        """
        text_lower = query_text.lower().strip()

        if not text_lower:
            return None

        # ── todo_create: 创建提醒 (check FIRST — most specific pattern) ──
        todo_keywords = ("帮我记", "提醒我", "记一下", "加个提醒", "设个提醒")
        for kw in todo_keywords:
            if kw in text_lower:
                slots = self._extract_slots(query_text, VoiceIntent.TODO_CREATE)
                return NLUResult(
                    intent=VoiceIntent.TODO_CREATE,
                    confidence=0.90,
                    slots=slots,
                    evidence=f"Keyword '{kw}' matched as todo_create",
                    method="rule",
                )

        # ── promise_tracker: 承诺追踪 ──
        promise_keywords = ("承诺", "答应", "待办", "还没做", "欠", "该做", "没完成")
        for kw in promise_keywords:
            if kw in text_lower:
                slots = self._extract_slots(query_text, VoiceIntent.PROMISE_TRACKER)
                return NLUResult(
                    intent=VoiceIntent.PROMISE_TRACKER,
                    confidence=0.90,
                    slots=slots,
                    evidence=f"Keyword '{kw}' matched as promise_tracker",
                    method="rule",
                )

        # ── relationship_status: 关系状态 ──
        relationship_keywords = ("关系", "进展", "到哪步了", "怎么样", "最近如何", "联系情况")
        for kw in relationship_keywords:
            if kw in text_lower:
                slots = self._extract_slots(query_text, VoiceIntent.RELATIONSHIP_STATUS)
                return NLUResult(
                    intent=VoiceIntent.RELATIONSHIP_STATUS,
                    confidence=0.90,
                    slots=slots,
                    evidence=f"Keyword '{kw}' matched as relationship_status",
                    method="rule",
                )

        # ── action_suggestion: 行动建议 ──
        action_keywords = ("建议", "该做什么", "下一步", "怎么推进", "我该怎么办", "该联系")
        for kw in action_keywords:
            if kw in text_lower:
                return NLUResult(
                    intent=VoiceIntent.ACTION_SUGGESTION,
                    confidence=0.88,
                    slots={},
                    evidence=f"Keyword '{kw}' matched as action_suggestion",
                    method="rule",
                )

        # ── schedule_query / schedule_range: 日程查询 (check AFTER specific intents) ──
        schedule_keywords = ("今天", "明天", "后天", "会议", "安排", "日程", "计划", "有什么会", "行程")
        for kw in schedule_keywords:
            if kw in text_lower:
                slots = self._extract_slots(query_text, VoiceIntent.SCHEDULE_QUERY)
                return NLUResult(
                    intent=VoiceIntent.SCHEDULE_QUERY,
                    confidence=0.92,
                    slots=slots,
                    evidence=f"Keyword '{kw}' matched as schedule_query",
                    method="rule",
                )

        # ── exit: 退出 ──
        exit_keywords = ("再见", "结束", "不用了", "拜拜", "退出", "没了")
        for kw in exit_keywords:
            if kw in text_lower:
                return NLUResult(
                    intent=VoiceIntent.EXIT,
                    confidence=0.95,
                    slots={},
                    evidence=f"Keyword '{kw}' matched as exit",
                    method="rule",
                )

        # ── chitchat detection ──
        chitchat_keywords = (
            "你好", "谢谢", "嗨", "早上好", "晚上好", "哈哈", "嗯嗯", "哦哦",
        )
        for kw in chitchat_keywords:
            if kw in text_lower:
                return NLUResult(
                    intent=VoiceIntent.CHITCHAT,
                    confidence=0.85,
                    slots={},
                    evidence=f"Keyword '{kw}' matched as chitchat",
                    method="rule",
                )

        # No rule match — return low confidence to trigger LLM fallback
        return NLUResult(
            intent=VoiceIntent.UNCLEAR,
            confidence=0.40,
            slots={},
            evidence="No keyword rule matched",
            method="rule",
        )

    async def _llm_classify(self, query_text: str) -> NLUResult:
        """Stage 2: LLM-based classification."""
        prompt = (
            "你是一个语音意图分类器。将用户的语音转写文字归类为以下9种意图之一。\n\n"
            "意图列表:\n"
            "- schedule_query: 日程查询（今天/明天有什么会议、安排）\n"
            "- schedule_range: 范围日程查询（本周/下周的日程）\n"
            "- promise_tracker: 承诺追踪（答应谁什么还没做、待办事项）\n"
            "- relationship_status: 关系状态查询（某人的关系进展、到哪步了）\n"
            "- action_suggestion: 行动建议（该做什么、下一步怎么走）\n"
            "- todo_create: 创建提醒（帮我记、提醒我）\n"
            "- unclear: 意图不明确\n"
            "- chitchat: 闲聊（你好、谢谢等，不处理业务逻辑）\n"
            "- exit: 退出对话（再见、结束、不用了）\n\n"
            f"用户输入: {query_text}\n\n"
            '只返回JSON: {"intent": "xxx", "confidence": 0.xx, "slots": {}, "evidence": "理由"}'
        )

        try:
            response = await self.llm.call_json(prompt=prompt, temperature=0.1)
        except Exception as exc:
            logger.warning(
                "nlu_llm_classify_failed",
                error=str(exc)[:200],
            )
            return NLUResult(
                intent=VoiceIntent.UNCLEAR,
                confidence=0.30,
                slots={},
                evidence=f"LLM classification failed: {str(exc)[:100]}",
                method="llm",
            )

        # Parse response
        try:
            intent_str = response.get("intent", "unclear")
            confidence = float(response.get("confidence", 0.5))
            slots_raw = response.get("slots", {})
            evidence = str(response.get("evidence", ""))

            # Clamp confidence to [0, 1]
            confidence = max(0.0, min(1.0, confidence))

            # Map string to enum
            try:
                intent = VoiceIntent(intent_str)
            except ValueError:
                logger.warning(
                    "nlu_llm_invalid_intent",
                    raw_intent=intent_str,
                )
                intent = VoiceIntent.UNCLEAR
                evidence = f"LLM returned invalid intent '{intent_str}', defaulted to unclear"

            # Normalize slots
            if not isinstance(slots_raw, dict):
                slots_raw = {}

            return NLUResult(
                intent=intent,
                confidence=confidence,
                slots=slots_raw,
                evidence=evidence or "LLM classified",
                method="llm",
            )
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning(
                "nlu_llm_response_parse_error",
                error=str(exc)[:200],
            )
            return NLUResult(
                intent=VoiceIntent.UNCLEAR,
                confidence=0.20,
                slots={},
                evidence=f"Failed to parse LLM response: {str(exc)[:100]}",
                method="llm",
            )

    @staticmethod
    def _extract_slots(query_text: str, intent: VoiceIntent) -> dict[str, Any]:
        """Extract slot values from query text based on intent type.

        For schedule_query: extract date reference ('今天'/'明天'/ISO date).
        For relationship_status / promise_tracker: extract person name.
        For todo_create: extract content and optional date/person.
        """
        slots: dict[str, Any] = {}
        text = query_text.strip()

        if intent == VoiceIntent.SCHEDULE_QUERY:
            # Date extraction
            today = date.today()
            if "今天" in text:
                slots["date"] = today.isoformat()
            elif "明天" in text:
                slots["date"] = (today + timedelta(days=1)).isoformat()
            elif "后天" in text:
                slots["date"] = (today + timedelta(days=2)).isoformat()
            elif "本周" in text or "这周" in text:
                slots["date_range"] = {
                    "start": today.isoformat(),
                    "end": (today + timedelta(days=6 - today.weekday())).isoformat(),
                }
            elif "下周" in text:
                next_monday = today + timedelta(days=7 - today.weekday())
                slots["date_range"] = {
                    "start": next_monday.isoformat(),
                    "end": (next_monday + timedelta(days=6)).isoformat(),
                }
            else:
                # Try ISO date pattern
                iso_match = re.search(r"\d{4}-\d{2}-\d{2}", text)
                if iso_match:
                    slots["date"] = iso_match.group()

        elif intent in (VoiceIntent.RELATIONSHIP_STATUS, VoiceIntent.PROMISE_TRACKER):
            # Person name extraction — look for patterns like "张总", "李经理", or "王三"
            # Title suffixes: multi-char first (经理/总工), then single-char
            name_match = re.search(
                r"[张王李赵刘陈杨黄周吴徐孙马朱胡郭何林高罗郑梁谢唐许韩冯邓曹彭曾萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施洪季季童毕栗耿鲁葛安伍辛詹时焦蒲柏曲松柳费卞柴宫翁牛羊巴甄井储衣吉龙]"
                r"(?:经理|总工|老板|先生|女士|老师|[总姐哥弟妹]|[\u4e00-\u9fff])",
                text,
            )
            if name_match:
                matched = name_match.group()
                # Filter out false positives from date words like 周一~周日
                if matched not in ("周一", "周二", "周三", "周四", "周五", "周六", "周日"):
                    slots["person"] = matched

        elif intent == VoiceIntent.TODO_CREATE:
            # Extract reminder content after keywords
            for kw in ("帮我记", "提醒我", "记一下", "加个提醒", "设个提醒"):
                idx = text.find(kw)
                if idx != -1:
                    content = text[idx + len(kw):].strip()
                    if content:
                        slots["content"] = content
                        break

            # Also extract person name from content
            content = slots.get("content", text)
            name_matches = re.findall(
                r"[张王李赵刘陈杨黄周吴徐孙马朱胡郭何林高罗郑梁谢唐许韩冯邓曹彭曾萧田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施洪季季童毕栗耿鲁葛安伍辛詹时焦蒲柏曲松柳费卞柴宫翁牛羊巴甄井储衣吉龙]"
                r"(?:经理|总工|老板|先生|女士|老师|[总姐哥弟妹]|[\u4e00-\u9fff])",
                content,
            )
            # Filter out date words; prefer matches with title suffix
            date_words = {"周一", "周二", "周三", "周四", "周五", "周六", "周日"}
            title_suffixes = {"经理", "总工", "老板", "先生", "女士", "老师", "总", "姐", "哥", "弟", "妹"}
            for matched in name_matches:
                if matched in date_words:
                    continue
                slots["person"] = matched
                # Prefer title-suffixed names; if found one, stop
                if any(matched.endswith(t) for t in title_suffixes):
                    break

            # Date extraction for todo
            day_map = {"今天": 0, "明天": 1, "后天": 2, "周五": 4, "周六": 5, "周日": 6}
            for day_name, offset in day_map.items():
                if day_name in text:
                    slots["due_date"] = (date.today() + timedelta(days=offset)).isoformat()
                    break

        return slots
