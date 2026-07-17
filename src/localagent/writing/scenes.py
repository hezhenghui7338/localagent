"""Scene taste packs for one-click polish."""

from __future__ import annotations

from dataclasses import dataclass

SCENE_EMAIL = "email"
SCENE_MOMENTS = "moments"
SCENE_RESUME = "resume"
SCENE_BIZ = "biz"

SCENE_IDS = (SCENE_EMAIL, SCENE_MOMENTS, SCENE_RESUME, SCENE_BIZ)

SCENE_ALIASES: dict[str, str] = {
    "email": SCENE_EMAIL,
    "mail": SCENE_EMAIL,
    "邮件": SCENE_EMAIL,
    "moments": SCENE_MOMENTS,
    "moment": SCENE_MOMENTS,
    "朋友圈": SCENE_MOMENTS,
    "wechat": SCENE_MOMENTS,
    "resume": SCENE_RESUME,
    "cv": SCENE_RESUME,
    "简历": SCENE_RESUME,
    "biz": SCENE_BIZ,
    "business": SCENE_BIZ,
    "商务": SCENE_BIZ,
    "企微": SCENE_BIZ,
    "im": SCENE_BIZ,
}


@dataclass(frozen=True)
class ScenePack:
    id: str
    label: str
    default_attitude: str
    hard_rules: tuple[str, ...]
    banned_phrases: tuple[str, ...]
    soft_label: str = "更软"
    firm_label: str = "更硬"


SCENE_PACKS: dict[str, ScenePack] = {
    SCENE_EMAIL: ScenePack(
        id=SCENE_EMAIL,
        label="商务邮件",
        default_attitude="清晰、可行动、礼貌；催促时留台阶",
        hard_rules=(
            "保留原文称呼、署名位置与已有事实（日期、人名、数字）",
            "不发明承诺、截止日或对方未说过的安排",
            "开头点明目的，结尾给出明确下一步或请求",
        ),
        banned_phrases=("首先其次最后", "在当今快节奏的", "赋能", "闭环落地"),
        soft_label="更软",
        firm_label="更硬",
    ),
    SCENE_MOMENTS: ScenePack(
        id=SCENE_MOMENTS,
        label="朋友圈",
        default_attitude="真诚、有画面、克制营销感",
        hard_rules=(
            "宜短；保留一个具体情绪或画面锚点",
            "不写成广告或鸡汤长文",
            "不新增原文没有的经历或地点",
        ),
        banned_phrases=("岁月静好", "人生没有白走的路", "干货满满", "冲鸭"),
        soft_label="更淡",
        firm_label="更燃",
    ),
    SCENE_RESUME: ScenePack(
        id=SCENE_RESUME,
        label="简历",
        default_attitude="成果导向、动词开头、可核验",
        hard_rules=(
            "禁止编造公司、职位、数字、客户名或技术栈",
            "原文没有量化数据时，只改表述，绝不补数字",
            "优先「动作 + 对象 + 结果」；删空话",
        ),
        banned_phrases=("负责相关工作", "熟悉各类", "具有较强的", "吃苦耐劳"),
        soft_label="更稳",
        firm_label="更亮",
    ),
    SCENE_BIZ: ScenePack(
        id=SCENE_BIZ,
        label="商务对话",
        default_attitude="专业、边界清晰、适合 IM/企微短消息",
        hard_rules=(
            "短句为主；一次只推进一件事",
            "不发明对方立场或已达成的共识",
            "语气得体，避免指责与阴阳",
        ),
        banned_phrases=("如上所述", "综上所述", "敬请知悉并"),
        soft_label="更软",
        firm_label="更硬",
    ),
}


def normalize_scene(raw: str | None) -> str | None:
    """Map user/LLM scene token to a canonical id, or None if unknown."""
    if raw is None:
        return None
    key = str(raw).strip().lower()
    if not key:
        return None
    if key in SCENE_PACKS:
        return key
    return SCENE_ALIASES.get(key) or SCENE_ALIASES.get(str(raw).strip())


def get_scene_pack(scene_id: str) -> ScenePack:
    sid = normalize_scene(scene_id) or SCENE_BIZ
    return SCENE_PACKS[sid]


def heuristic_scene(text: str) -> tuple[str, float]:
    """Cheap keyword-based scene guess. Returns (scene_id, confidence)."""
    t = text or ""
    low = t.lower()
    scores = {
        SCENE_EMAIL: 0,
        SCENE_MOMENTS: 0,
        SCENE_RESUME: 0,
        SCENE_BIZ: 0,
    }
    email_hits = ("主题:", "subject:", "尊敬的", "此致", "您好", "邮件", "cc:", "to:")
    moments_hits = ("朋友圈", "#", "打卡", "分享一下", "今日份")
    resume_hits = ("负责", "主导", "任职", "简历", "实习", "工作经历", "项目经历", "kpi")
    biz_hits = ("企微", "对齐一下", "同步下", "方便时", "麻烦", "收到请回复")

    for h in email_hits:
        if h in low or h in t:
            scores[SCENE_EMAIL] += 1
    for h in moments_hits:
        if h in low or h in t:
            scores[SCENE_MOMENTS] += 1
    for h in resume_hits:
        if h in low or h in t:
            scores[SCENE_RESUME] += 1
    for h in biz_hits:
        if h in low or h in t:
            scores[SCENE_BIZ] += 1

    # Length heuristic: very short → biz/moments; long structured → email/resume
    if len(t) < 80:
        scores[SCENE_BIZ] += 1
        scores[SCENE_MOMENTS] += 0.5
    if "\n" in t and len(t) > 120:
        scores[SCENE_EMAIL] += 0.5

    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score <= 0:
        return SCENE_BIZ, 0.35
    total = sum(scores.values()) or 1.0
    conf = min(0.95, 0.4 + (best_score / total) * 0.5)
    return best, conf
