"""
ゲーム設定 / エリアサイズプリセット / 難易度プリセット

変更方法:
  CURRENT_AREA   = "small" / "medium" / "large"  ← マップ規模を切り替える
  CURRENT_PRESET = "easy"  / "normal" / "hard"   ← 難易度を上書き調整する

適用優先順位: _DEFAULTS  <  AREA_PRESETS  <  PRESETS
"""

# --- デフォルト値（どのプリセットにも含まれない項目のフォールバック）---
_DEFAULTS = {
    "MAP_W":                10,
    "MAP_H":                10,
    "WALL_MIN":             15,
    "WALL_MAX":             22,
    "SURVIVE_TURNS":        30,
    "PLAYER_MAX_HP":        100,
    "PLAYER_ATK":           20,
    "ENEMY_MAX_HP":         30,
    "ENEMY_ATK":            10,
    "MISS_RATE":            0.10,
    "CRITICAL_RATE":        0.20,
    "HEAL_AMOUNT":          30,
    "INITIAL_ITEM_COUNT":   2,
    "MAX_INVENTORY":        2,
    "KILL_BONUS":           10,
    "ENEMY_SPAWN_INTERVAL": 5,
    "MAX_ACTIVE_ENEMIES":   3,
    "BOSS_HP_MULTIPLIER":   3,    # ボスHP = ENEMY_MAX_HP × 3
    "BOSS_ATK_MULTIPLIER":  2,    # ボスATK = ENEMY_ATK × 2
    "BOSS_KILL_BONUS":      50,   # ボス撃破スコアボーナス
    "BOSS_SPAWN_OFFSET":    10,   # SURVIVE_TURNS - この値 のターンでボス出現
    "ENEMY_CHASE_RATE":     0.7,  # 敵がプレイヤー方向へ近づく確率（0.0=完全ランダム, 1.0=常に追尾）
    "DAMAGE_VARIANCE_RATE": 0.2,  # 通常ダメージの振れ幅（ATK ± この割合: 0.0=固定, 0.2=±20%）
}

# --- エリアサイズプリセット ---
# 壁数は総マス数の 15〜22% を目安に設定
AREA_PRESETS = {
    "small": {
        "MAP_W":                8,
        "MAP_H":                8,
        "WALL_MIN":             10,    # ~15.6% of 64
        "WALL_MAX":             14,    # ~21.9% of 64
        "SURVIVE_TURNS":        30,
        "MAX_ACTIVE_ENEMIES":   2,
        "ENEMY_SPAWN_INTERVAL": 5,
        "INITIAL_ITEM_COUNT":   3,     # MIN 3 でインベントリ満タン検証が成立
    },
    "medium": {
        "MAP_W":                10,
        "MAP_H":                10,
        "WALL_MIN":             15,    # 15.0% of 100
        "WALL_MAX":             22,    # 22.0% of 100
        "SURVIVE_TURNS":        100,
        "MAX_ACTIVE_ENEMIES":   3,
        "ENEMY_SPAWN_INTERVAL": 5,
        "INITIAL_ITEM_COUNT":   5,
    },
    "large": {
        "MAP_W":                15,
        "MAP_H":                15,
        "WALL_MIN":             34,    # ~15.1% of 225
        "WALL_MAX":             50,    # ~22.2% of 225
        "SURVIVE_TURNS":        200,
        "MAX_ACTIVE_ENEMIES":   5,
        "ENEMY_SPAWN_INTERVAL": 5,
        "INITIAL_ITEM_COUNT":   8,
    },
}

CURRENT_AREA = "medium"

# --- 難易度プリセット（AREA_PRESETS の値を上書きして難易度だけ変える）---
PRESETS = {
    "easy":   {"SURVIVE_TURNS": 30},
    "normal": {},                      # エリアのデフォルト値をそのまま使用
    "hard":   {"SURVIVE_TURNS": 200},
}

CURRENT_PRESET = "normal"

# --- 優先順位: _DEFAULTS < AREA_PRESETS < PRESETS ---
_cfg = {**_DEFAULTS, **AREA_PRESETS.get(CURRENT_AREA, {}), **PRESETS.get(CURRENT_PRESET, {})}

MAP_W                = _cfg["MAP_W"]
MAP_H                = _cfg["MAP_H"]
WALL_MIN             = _cfg["WALL_MIN"]
WALL_MAX             = _cfg["WALL_MAX"]
SURVIVE_TURNS        = _cfg["SURVIVE_TURNS"]
PLAYER_MAX_HP        = _cfg["PLAYER_MAX_HP"]
PLAYER_ATK           = _cfg["PLAYER_ATK"]
ENEMY_MAX_HP         = _cfg["ENEMY_MAX_HP"]
ENEMY_ATK            = _cfg["ENEMY_ATK"]
MISS_RATE            = _cfg["MISS_RATE"]
CRITICAL_RATE        = _cfg["CRITICAL_RATE"]
HEAL_AMOUNT          = _cfg["HEAL_AMOUNT"]
INITIAL_ITEM_COUNT   = _cfg["INITIAL_ITEM_COUNT"]
MAX_INVENTORY        = _cfg["MAX_INVENTORY"]
KILL_BONUS           = _cfg["KILL_BONUS"]
ENEMY_SPAWN_INTERVAL = _cfg["ENEMY_SPAWN_INTERVAL"]
MAX_ACTIVE_ENEMIES   = _cfg["MAX_ACTIVE_ENEMIES"]
BOSS_HP_MULTIPLIER   = _cfg["BOSS_HP_MULTIPLIER"]
BOSS_ATK_MULTIPLIER  = _cfg["BOSS_ATK_MULTIPLIER"]
BOSS_KILL_BONUS      = _cfg["BOSS_KILL_BONUS"]
BOSS_SPAWN_OFFSET    = _cfg["BOSS_SPAWN_OFFSET"]
ENEMY_CHASE_RATE     = _cfg["ENEMY_CHASE_RATE"]
DAMAGE_VARIANCE_RATE = _cfg["DAMAGE_VARIANCE_RATE"]
