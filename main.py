#!/usr/bin/env python3
"""
軽量ローグライク - フェーズ5：研修用不具合機能
仕様: roguelike_spec.md v1.8

実装範囲:
  - グリッドマップ（サイズは config.py の CURRENT_AREA で切替: §4.6）
  - W/A/S/D 移動（仕様 §6.1）
  - 壁・ランダム配置・通行不可（仕様 §4.3）
  - 敵1体（仕様 §5.2 / フェーズ1は3体→1体）
  - プレイヤーHP（仕様 §5.1）
  - 戦闘: ミス(10%) / クリティカル(20%, 2倍) / 固定ダメージ（仕様 §8.2）
  - 規定ターン生存でクリア / HP≤0 でゲームオーバー（仕様 §3）
  - Rキーでリスタート（仕様 §9.1）
  - 回復薬の配置・自動取得・インベントリ・H/X操作（仕様 §11）

フェーズ3 追加:
  - 回復薬の初期配置（仕様 §11.2）
  - 移動時の自動取得（仕様 §7.1 [2b] / §11.3）
  - インベントリ最大2（仕様 §5.1 / TBD-21）
  - H キーで使用（仕様 §11.4）
  - X キーで破棄（仕様 §11.5）

フェーズ4 追加:
  - スコア計算・表示（仕様 §12）

フェーズ5 追加:
  - INTENTIONAL_BUGS フラグによる不具合ON/OFF切替（研修用）
"""

import os
import sys
import random
from collections import deque

from config import (
    MAP_W, MAP_H, WALL_MIN, WALL_MAX, CURRENT_AREA,
    SURVIVE_TURNS,
    PLAYER_MAX_HP, PLAYER_ATK,
    ENEMY_MAX_HP, ENEMY_ATK,
    MISS_RATE, CRITICAL_RATE,
    HEAL_AMOUNT, INITIAL_ITEM_COUNT, MAX_INVENTORY,
    KILL_BONUS,
    ENEMY_SPAWN_INTERVAL, MAX_ACTIVE_ENEMIES,
    BOSS_HP_MULTIPLIER, BOSS_ATK_MULTIPLIER, BOSS_KILL_BONUS, BOSS_SPAWN_OFFSET,
    ENEMY_CHASE_RATE,
    DAMAGE_VARIANCE_RATE,
)

# ============================================================
# 定数（マップ定数は config.py の AREA_PRESETS から取得）
# ============================================================
MAP_MAX_RETRY       = 100  # 仕様 §4.4.1: マップ生成の最大リトライ回数
ENEMY_COUNT         = 1    # フェーズ1: 1体（仕様では3体）
CRITICAL_MULTIPLIER = 2.0  # クリティカル時のダメージ倍率（仕様 §8.2.1）

# ============================================================
# 研修用不具合設定（フェーズ5）
#
# 有効にしたいバグIDをセットに追加してゲームを起動する。
# 例: INTENTIONAL_BUGS = {'BUG-01', 'BUG-03'}
# 全OFF（仕様通り正常動作）: INTENTIONAL_BUGS = set()
#
# BUG-01 GAMEOVER_SKIP        HP≤0でもゲームオーバーにならない
# BUG-02 WALL_PASSTHROUGH     30%の確率で壁をすり抜ける
# BUG-03 CRIT_MULTIPLIER_WEAK クリティカル倍率が1.5x（仕様は2.0x）
# BUG-04 INVENTORY_OVERFLOW   インベントリ上限なしで取得できる
# BUG-05 WIN_LOSE_REVERSED    勝敗同時成立時にCLEARが優先（敗北優先が逆）
# BUG-06 MISS_DEALS_DAMAGE    ミスでも固定ダメージが入る
# ============================================================
INTENTIONAL_BUGS: set = set()   # ← ここを変更して不具合を有効化

# マップ表示文字（仕様 §15.3）
FLOOR      = '.'
WALL_CHAR  = '#'
SYM_PLAYER = 'P'
SYM_ENEMY  = 'E'
SYM_ITEM   = '!'  # 回復薬（仕様 §15.3）
SYM_BOSS   = 'B'  # ボス敵

# ゲーム状態（仕様 §9.1）
PLAYING  = 'playing'
CLEAR    = 'clear'
GAMEOVER = 'gameover'


# ============================================================
# 入力（仕様 §15.1）
# 1キー即時入力（Enter不要）、OS別実装
# ============================================================
def getch():
    if os.name == 'nt':
        import msvcrt
        ch = msvcrt.getch()
        try:
            return ch.decode('ascii').lower()
        except (UnicodeDecodeError, ValueError):
            return ''
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return ch.lower()


# ============================================================
# マップ生成（仕様 §4.3, §4.4 MAP-00〜05）
# フェーズ1: フォールバック処理は除外
# ============================================================
def _passable(grid, x, y):
    return 0 <= x < MAP_W and 0 <= y < MAP_H and grid[y][x] == FLOOR


def _has_free_neighbor(grid, x, y):
    """仕様 MAP-04/05: 周囲4マスに通行可能マスが1つ以上あるか"""
    return any(_passable(grid, x+dx, y+dy) for dx, dy in ((0,-1),(0,1),(-1,0),(1,0)))


def _bfs_reachable(grid, sx, sy):
    """仕様 MAP-03: BFSでプレイヤー位置から到達可能なマス集合を返す"""
    visited = {(sx, sy)}
    q = deque([(sx, sy)])
    while q:
        x, y = q.popleft()
        for dx, dy in ((0,-1),(0,1),(-1,0),(1,0)):
            nx, ny = x+dx, y+dy
            if (nx, ny) not in visited and _passable(grid, nx, ny):
                visited.add((nx, ny))
                q.append((nx, ny))
    return visited


def generate_map():
    """
    マップ・プレイヤー・敵の初期配置を生成する。
    MAP-00〜05 のバリデーションで違反したら再生成（最大 MAP_MAX_RETRY 回）。
    フェーズ1: フォールバック処理は未実装（仕様 §4.4.2 は除外）。
    """
    for _ in range(MAP_MAX_RETRY):
        # 空マップ作成
        grid = [[FLOOR] * MAP_W for _ in range(MAP_H)]

        # 壁をランダム配置（仕様 §4.3）
        n_walls = random.randint(WALL_MIN, WALL_MAX)
        all_cells = [(x, y) for y in range(MAP_H) for x in range(MAP_W)]
        for wx, wy in random.sample(all_cells, n_walls):
            grid[wy][wx] = WALL_CHAR

        # MAP-00: 壁マス数が 15〜20 の範囲内か確認
        actual_walls = sum(grid[y][x] == WALL_CHAR for y in range(MAP_H) for x in range(MAP_W))
        if not (WALL_MIN <= actual_walls <= WALL_MAX):
            continue

        # 通行可能マスからプレイヤー・敵の位置をランダム選択（仕様 §4.5）
        free = [(x, y) for y in range(MAP_H) for x in range(MAP_W) if grid[y][x] == FLOOR]
        if len(free) < 1 + ENEMY_COUNT:
            continue

        positions = random.sample(free, 1 + ENEMY_COUNT)
        px, py = positions[0]
        enemy_starts = positions[1:]

        # MAP-01/02: free リストから選んでいるため壁マスは自動除外済み

        # MAP-04: プレイヤー周囲4マスに通行可能マスが1つ以上
        if not _has_free_neighbor(grid, px, py):
            continue

        # MAP-05: 各敵の周囲4マスに通行可能マスが1つ以上
        if not all(_has_free_neighbor(grid, ex, ey) for ex, ey in enemy_starts):
            continue

        # MAP-03: BFS でプレイヤーから全敵への経路が存在する
        reachable = _bfs_reachable(grid, px, py)
        if not all((ex, ey) in reachable for ex, ey in enemy_starts):
            continue

        # 全バリデーション通過
        return grid, (px, py), enemy_starts

    # フォールバックなし（実運用では100回以内に必ず成立する想定）
    raise RuntimeError(f"マップ生成に {MAP_MAX_RETRY} 回失敗しました")


def place_items(grid, px, py, enemy_starts):
    """
    マップ上に回復薬を INITIAL_ITEM_COUNT 個ランダム配置する。
    仕様 §11.2: 壁マス・プレイヤー初期マス・敵初期マスを除くフロアマスに配置。
    """
    occupied = {(px, py)} | set(enemy_starts)
    free = [
        (x, y)
        for y in range(MAP_H) for x in range(MAP_W)
        if grid[y][x] == FLOOR and (x, y) not in occupied
    ]
    n = min(INITIAL_ITEM_COUNT, len(free))  # 空きが少ない場合は配置可能数に制限
    return [{'x': x, 'y': y} for x, y in random.sample(free, n)]


# ============================================================
# 敵スポーン（仕様 §16）
# ============================================================
def try_spawn_enemy(grid, player, enemies, items):
    """
    生存敵数が MAX_ACTIVE_ENEMIES 未満のとき、プレイヤーから
    BFS到達可能なフロアマスに敵を1体スポーンする。
    スポーン不可能な場合（候補マスなし・上限到達）は何もしない。
    返値: スポーン成功時は表示メッセージ文字列、失敗時は None
    """
    alive = [e for e in enemies if e['hp'] > 0]
    if len(alive) >= MAX_ACTIVE_ENEMIES:
        return None

    occupied = {(player['x'], player['y'])}
    occupied |= {(e['x'], e['y']) for e in alive}
    occupied |= {(item['x'], item['y']) for item in items}

    reachable = _bfs_reachable(grid, player['x'], player['y'])
    candidates = [(x, y) for (x, y) in reachable if (x, y) not in occupied]

    if not candidates:
        return None

    sx, sy = random.choice(candidates)
    enemies.append({
        'x': sx, 'y': sy,
        'hp': ENEMY_MAX_HP, 'max_hp': ENEMY_MAX_HP,
        'atk': ENEMY_ATK, 'is_boss': False,
    })
    return '敵が出現した！'


# ============================================================
# ボス出現（SURVIVE_TURNS - BOSS_SPAWN_OFFSET ターンで1度だけ）
# ============================================================
def try_spawn_boss(grid, player, enemies, items):
    """
    ボスを1体スポーンする。MAX_ACTIVE_ENEMIES の制限は受けない。
    スポーン位置は通常敵と同じルール（壁・プレイヤー・既存敵・アイテムを除外）。
    返値: スポーン成功時はメッセージ文字列、失敗時（候補なし）は None
    """
    occupied = {(player['x'], player['y'])}
    occupied |= {(e['x'], e['y']) for e in enemies if e['hp'] > 0}
    occupied |= {(item['x'], item['y']) for item in items}

    reachable  = _bfs_reachable(grid, player['x'], player['y'])
    candidates = [(x, y) for (x, y) in reachable if (x, y) not in occupied]

    if not candidates:
        return None

    bx, by   = random.choice(candidates)
    boss_hp  = ENEMY_MAX_HP * BOSS_HP_MULTIPLIER
    boss_atk = ENEMY_ATK * BOSS_ATK_MULTIPLIER
    enemies.append({
        'x': bx, 'y': by,
        'hp': boss_hp, 'max_hp': boss_hp,
        'atk': boss_atk, 'is_boss': True,
    })
    return f'【ボス出現！】残り{BOSS_SPAWN_OFFSET}ターン ― 強敵が現れた！'


# ============================================================
# 描画（仕様 §15.2, §15.2.1, §15.2.2, §15.3）
# ============================================================
def render(grid, player, enemies, items, state, turn, message=''):
    # ANSIエスケープで画面クリア（仕様 §15.2）
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()

    hp    = player['hp']
    inv   = player['inventory']
    kills = player['kills'] + player['boss_kills']
    # スコア = 通常撃破 × KILL_BONUS + ボス撃破 × BOSS_KILL_BONUS + 経過ターン数
    score = player['kills'] * KILL_BONUS + player['boss_kills'] * BOSS_KILL_BONUS + turn
    alive = [e for e in enemies if e['hp'] > 0]

    # ヘッダー（仕様 §15.2.1）
    print("==== Roguelike v1.0 [Phase 5] ====")
    meta = f"[Area: {CURRENT_AREA}]"
    if INTENTIONAL_BUGS:
        meta += f"  [BUGS: {', '.join(sorted(INTENTIONAL_BUGS))}]"
    print(meta)
    print(f"Turn: {turn:2d} / {SURVIVE_TURNS}    Score: {score:3d}    Kills: {kills}")
    print(f"HP:   {hp:3d} / {PLAYER_MAX_HP}    Inv: {inv} / {MAX_INVENTORY}")
    if alive:
        # ボスが生存していれば優先表示
        e     = next((e for e in alive if e.get('is_boss')), alive[0])
        label = 'Boss ' if e.get('is_boss') else 'Enemy'
        sym   = SYM_BOSS if e.get('is_boss') else SYM_ENEMY
        print(f"{label} HP: {e['hp']:2d} / {e['max_hp']}    "
              f"P:({player['x']},{player['y']})  {sym}:({e['x']},{e['y']})")
    else:
        print("Enemy: DEFEATED  （全撃破 ― 規定ターンまで継続）")
    print()

    # マップ描画（仕様 §15.3 / §15.3.1 表示優先度: P > E > ! > .）
    display = [row[:] for row in grid]
    for item in items:
        display[item['y']][item['x']] = SYM_ITEM   # 回復薬
    for e in enemies:
        if e['hp'] > 0:
            display[e['y']][e['x']] = SYM_BOSS if e.get('is_boss') else SYM_ENEMY
    display[player['y']][player['x']] = SYM_PLAYER  # プレイヤーが最高優先

    for row in display:
        print(' '.join(row))
    print()

    # 状態別フッター（仕様 §15.2.2）
    if state == CLEAR:
        print(f"*** CLEAR! Score: {score} ***")
        print("[R] Restart  [Q] Quit")
    elif state == GAMEOVER:
        print(f"*** GAME OVER  Score: {score} ***")
        print("[R] Restart  [Q] Quit")
    else:
        print("[W/A/S/D] 移動  [H] 回復薬使用  [X] 回復薬破棄")

    if message:
        print(f">> {message}")


# ============================================================
# 戦闘（仕様 §8）
# フェーズ2: ミス / クリティカル / 通常攻撃の3パターン
# ============================================================
def do_combat(atk, defender):
    """
    atk で defender を攻撃する。

    判定順序（仕様 §8.2.2）:
      [1] ミス判定（MISS_RATE=10%）
            成立 → damage=0、以降スキップ（仕様 E-08）
      [2] 基礎ダメージ決定（ATK ± DAMAGE_VARIANCE_RATE, 最小1）
      [3] クリティカル判定（CRITICAL_RATE=20%）
            成立 → damage = base × CRITICAL_MULTIPLIER
      [4] 通常攻撃 → damage = base

    返値: (damage, is_killed, result)
      result: 'miss' / 'critical' / 'normal'
    仕様 §8.4.1: defender['hp'] は 0 でクランプ
    """
    # [1] ミス判定（仕様 §8.2.2 [1]）
    if random.random() < MISS_RATE:
        # BUG-06: ミスでも基礎ダメージが入る（ミス判定が機能しない）
        # 影響: ミス表示なのにHPが減る。確率検証でミス≒0%相当の挙動になる
        if 'BUG-06' in INTENTIONAL_BUGS:
            base = max(1, round(atk * random.uniform(
                1 - DAMAGE_VARIANCE_RATE, 1 + DAMAGE_VARIANCE_RATE)))
            defender['hp'] = max(0, defender['hp'] - base)
            return base, defender['hp'] <= 0, 'miss'
        return 0, False, 'miss'

    # [2] 基礎ダメージ決定（仕様 §8.2.2 [2]）
    base = max(1, round(atk * random.uniform(
        1 - DAMAGE_VARIANCE_RATE, 1 + DAMAGE_VARIANCE_RATE)))

    # [3] クリティカル判定（仕様 §8.2.2 [3]）
    if random.random() < CRITICAL_RATE:
        # BUG-03: クリティカル倍率が1.5x（仕様は2.0x）
        # 影響: クリティカル時ダメージが base×1.5 になる（base≈20なら40→30）
        multiplier = 1.5 if 'BUG-03' in INTENTIONAL_BUGS else CRITICAL_MULTIPLIER
        damage = int(base * multiplier)
        result = 'critical'
    else:
        damage = base
        result = 'normal'

    defender['hp'] = max(0, defender['hp'] - damage)  # 仕様 §8.4.1: 0クランプ
    return damage, defender['hp'] <= 0, result


def _fmt(result, damage):
    """攻撃結果を表示用文字列に変換"""
    if result == 'miss':
        return 'MISS'
    if result == 'critical':
        return f'CRITICAL!({damage})'
    return str(damage)


# ============================================================
# 敵の移動（仕様 §7.2 / §17）
# ============================================================
def move_enemy(enemy, grid, player, all_enemies):
    """
    敵の移動処理。ENEMY_CHASE_RATE の確率でプレイヤーへの追尾を試みる（仕様 §17）。
      - 追尾モード: マンハッタン距離が縮まる方向のうち有効なマスへランダムに移動
      - 追尾候補なし / 非追尾モード: 上下左右をランダムに試行するフォールバック
      - 壁 / マップ外 / 他の敵のマス: 無効（仕様 §7.2.2）
      - プレイヤーのマス: 有効として確定し戦闘発生（仕様 §7.2.3）
      - 有効マスがない場合: 静止（仕様 §7.2.2-4）
    返値: 'combat' / 'moved' / None
    """
    if enemy['hp'] <= 0:
        return None

    # 他の敵の座標（敵同士の重なり不許可: 仕様 §7.2.4）
    other_pos = {(e['x'], e['y']) for e in all_enemies if e is not enemy and e['hp'] > 0}
    px, py = player['x'], player['y']
    ex, ey = enemy['x'], enemy['y']
    cur_dist = abs(ex - px) + abs(ey - py)

    dirs = [(0,-1), (0,1), (-1,0), (1,0)]

    def can_enter(nx, ny):
        """壁・範囲外・他の敵がいないか（プレイヤーマスは別途判定）"""
        return (0 <= nx < MAP_W and 0 <= ny < MAP_H
                and grid[ny][nx] != WALL_CHAR
                and (nx, ny) not in other_pos)

    # --- 追尾モード（仕様 §17）---
    if random.random() < ENEMY_CHASE_RATE:
        chase_candidates = [
            (dx, dy) for dx, dy in dirs
            if abs((ex + dx) - px) + abs((ey + dy) - py) < cur_dist
            and (can_enter(ex + dx, ey + dy) or (ex + dx, ey + dy) == (px, py))
        ]
        if chase_candidates:
            random.shuffle(chase_candidates)
            dx, dy = chase_candidates[0]
            nx, ny = ex + dx, ey + dy
            if (nx, ny) == (px, py):
                return 'combat'
            enemy['x'], enemy['y'] = nx, ny
            return 'moved'
        # 追尾候補なし → ランダムにフォールバック

    # --- ランダム移動（フォールバック / 非追尾モード）---
    random.shuffle(dirs)
    for dx, dy in dirs:
        nx, ny = ex + dx, ey + dy
        if not (0 <= nx < MAP_W and 0 <= ny < MAP_H):  # マップ外（仕様 §7.2.2）
            continue
        if grid[ny][nx] == WALL_CHAR:                  # 壁（仕様 §7.2.2）
            continue
        if (nx, ny) in other_pos:                       # 他の敵（仕様 §7.2.4）
            continue
        if (nx, ny) == (px, py):
            return 'combat'
        enemy['x'], enemy['y'] = nx, ny
        return 'moved'

    return None  # 4方向すべて無効 → 静止


# ============================================================
# 勝敗判定（仕様 §3.3 / §7.1 [3][5][7]）
# ============================================================
def check_outcome(player, turn):
    """敗北チェックを先行させる（仕様 §3.3: 同時成立は敗北優先）"""
    # BUG-05: 勝敗判定の優先順位が逆（CLEAR を先に確認してしまう）
    # 影響: turn=30 かつ HP≤0 のとき、仕様では敗北だがCLEARになる
    if 'BUG-05' in INTENTIONAL_BUGS:
        if turn >= SURVIVE_TURNS:
            return CLEAR
        if player['hp'] <= 0:
            return GAMEOVER
        return None

    # 正常: 敗北を先に確認（仕様 §3.3）
    # BUG-01: HP≤0 でも GAMEOVER を返さない（敗北条件を無視）
    # 影響: HP=0 のままプレイが継続できる
    if player['hp'] <= 0 and 'BUG-01' not in INTENTIONAL_BUGS:
        return GAMEOVER
    if turn >= SURVIVE_TURNS:
        return CLEAR
    return None


# ============================================================
# ゲーム初期化（仕様 §9.1.1）
# ============================================================
def init_game():
    grid, (px, py), enemy_starts = generate_map()
    player  = {'x': px, 'y': py, 'hp': PLAYER_MAX_HP, 'inventory': 0, 'kills': 0, 'boss_kills': 0}
    enemies = [
        {'x': ex, 'y': ey, 'hp': ENEMY_MAX_HP, 'max_hp': ENEMY_MAX_HP, 'atk': ENEMY_ATK, 'is_boss': False}
        for ex, ey in enemy_starts
    ]
    items        = place_items(grid, px, py, enemy_starts)
    boss_spawned = False
    return grid, player, enemies, items, 0, boss_spawned


# ============================================================
# メインループ（仕様 §7.1 ターン進行 [1]〜[7]）
# ============================================================
def main():
    grid, player, enemies, items, turn, boss_spawned = init_game()
    state   = PLAYING
    message = f'{SURVIVE_TURNS}ターン生き残れ！'

    while True:
        render(grid, player, enemies, items, state, turn, message)
        message = ''

        # ===== ゲーム終了状態: R / Q のみ受付（仕様 §6.2）=====
        if state != PLAYING:
            key = getch()
            if key == 'r':
                # リスタート: 全項目リセット（仕様 §9.1.1）
                grid, player, enemies, items, turn, boss_spawned = init_game()
                state   = PLAYING
                message = 'リスタート！'
            elif key == 'q':
                sys.stdout.write('\033[2J\033[H')
                print("ゲームを終了します。")
                break
            continue  # R/Q 以外は無視（仕様 §6.2）

        # ===== [1] 入力受付（プレイ中のみ）=====
        key = getch()

        move_dir = {'w': (0,-1), 's': (0,1), 'a': (-1,0), 'd': (1,0)}

        if key in move_dir:
            # ===== [2] 移動アクション =====
            dx, dy = move_dir[key]
            nx, ny = player['x'] + dx, player['y'] + dy

            # 移動先バリデーション（仕様 §6.4）
            if not (0 <= nx < MAP_W and 0 <= ny < MAP_H):
                message = '【マップ外には進めない】'
                continue  # ターン消費なし
            if grid[ny][nx] == WALL_CHAR:
                # BUG-02: 30%の確率で壁をすり抜ける
                # 影響: 壁通行不可テストが非決定的になる。ターン消費も発生する
                if 'BUG-02' in INTENTIONAL_BUGS and random.random() < 0.3:
                    pass  # すり抜け（移動続行）
                else:
                    message = '【壁がある！】'
                    continue  # ターン消費なし

            # 移動先に敵がいるか確認（仕様 §6.3）
            target = next((e for e in enemies if e['hp'] > 0 and e['x'] == nx and e['y'] == ny), None)
            moved = False  # 自動取得の判定に使用

            if target:
                # 移動先に敵 → 戦闘（仕様 §8.3: 移動してきた側 = プレイヤーが先攻）
                p_dmg, killed, p_res = do_combat(PLAYER_ATK, target)
                if killed:
                    player['x'], player['y'] = nx, ny
                    moved = True
                    if target.get('is_boss'):
                        player['boss_kills'] += 1
                        label = 'ボスを撃破'
                    else:
                        player['kills'] += 1
                        label = '敵を撃破'
                    score_now = player['kills'] * KILL_BONUS + player['boss_kills'] * BOSS_KILL_BONUS + turn
                    message = f'{label}！（与: {_fmt(p_res, p_dmg)}）  Score: {score_now}'
                else:
                    # 敵が生存 → 反撃（プレイヤーは移動しない）
                    e_dmg, _, e_res = do_combat(target['atk'], player)
                    message = (f'戦闘！ 与:{_fmt(p_res, p_dmg)} / 被:{_fmt(e_res, e_dmg)}'
                               f'  →  自HP: {player["hp"]}  敵HP: {target["hp"]}')
            else:
                # 通常移動（仕様 §6.3）
                player['x'], player['y'] = nx, ny
                moved = True

            # ===== [2b] 回復薬の自動取得（仕様 §7.1 [2b] / §11.3）=====
            # 移動が成立したときのみ、移動先マスのアイテムを確認する
            if moved:
                for item in items[:]:
                    if item['x'] == player['x'] and item['y'] == player['y']:
                        # BUG-04: インベントリ上限チェックを省略（上限なしで取得できる）
                        # 影響: MAX_INVENTORY=2 を超えて所持数が増える
                        if player['inventory'] < MAX_INVENTORY or 'BUG-04' in INTENTIONAL_BUGS:
                            # 取得成立（仕様 §11.3）
                            player['inventory'] += 1
                            items.remove(item)
                            pick_msg = f'回復薬を拾った！ 所持: {player["inventory"]}/{MAX_INVENTORY}'
                        else:
                            # 仕様 §11.3: 満タン時はアイテム残存、自動取得しない
                            pick_msg = f'インベントリ満タン！ 回復薬を拾えない（H/X で空きを作ること）'
                        message = (message + '  ' + pick_msg).strip() if message else pick_msg
                        break

        elif key == 'h':
            # ===== [2] 回復薬使用（仕様 §11.4）=====
            if player['inventory'] < 1:
                message = '【回復薬がない！ インベントリ: 0】'
                continue  # ターン消費なし（仕様 §11.7）
            # 仕様 §11.4: HP += HEAL_AMOUNT、MAX_HPでクランプ（HP満タン時も使用成立）
            player['hp'] = min(PLAYER_MAX_HP, player['hp'] + HEAL_AMOUNT)
            player['inventory'] -= 1
            message = f'回復薬使用！ HP: {player["hp"]}/{PLAYER_MAX_HP}  所持: {player["inventory"]}/{MAX_INVENTORY}'

        elif key == 'x':
            # ===== [2] 回復薬破棄（仕様 §11.5）=====
            if player['inventory'] < 1:
                message = '【破棄する回復薬がない！】'
                continue  # ターン消費なし（仕様 §11.7）
            player['inventory'] -= 1
            message = f'回復薬を破棄した。所持: {player["inventory"]}/{MAX_INVENTORY}'

        else:
            continue  # 定義外キーは無視・ターン消費なし（仕様 §6.2）

        # ===== [3] 勝敗判定（仕様 §7.1 [3]）=====
        outcome = check_outcome(player, turn)
        if outcome:
            state = outcome
            continue

        # ===== [4] 敵全体の行動（仕様 §7.1 [4]）=====
        for enemy in enemies:
            if enemy['hp'] <= 0:
                continue
            result = move_enemy(enemy, grid, player, enemies)
            if result == 'combat':
                # 敵がプレイヤーへ突撃 → 敵が先攻（仕様 §8.3）
                e_dmg, player_killed, e_res = do_combat(enemy['atk'], player)
                if player_killed:
                    attacker = 'ボスの攻撃！' if enemy.get('is_boss') else '敵の攻撃！'
                    message = f'{attacker} {_fmt(e_res, e_dmg)}ダメージ → 敗北...'
                    break  # 敗北確定: 残りの敵行動はスキップ
                # プレイヤー生存 → 反撃（仕様 §8.3）
                p_dmg, enemy_killed, p_res = do_combat(PLAYER_ATK, enemy)
                msg = f'{"ボス" if enemy.get("is_boss") else "敵"}が突撃！ 被:{_fmt(e_res, e_dmg)} / 反撃:{_fmt(p_res, p_dmg)}'
                if enemy_killed:
                    if enemy.get('is_boss'):
                        player['boss_kills'] += 1
                        msg += f'  → ボス撃破！  Score: {player["kills"] * KILL_BONUS + player["boss_kills"] * BOSS_KILL_BONUS + turn}'
                    else:
                        player['kills'] += 1
                        msg += f'  → 敵撃破！  Score: {player["kills"] * KILL_BONUS + player["boss_kills"] * BOSS_KILL_BONUS + turn}'
                message = (message + '  ' + msg).strip() if message else msg

        # ===== [5] 勝敗判定（仕様 §7.1 [5]）=====
        outcome = check_outcome(player, turn)
        if outcome:
            state = outcome
            continue

        # ===== [6] ターンカウント +1（仕様 §7.1 [6]）=====
        turn += 1

        # ===== [6b] 敵スポーン（仕様 §16: ENEMY_SPAWN_INTERVAL ターンごと）=====
        if turn % ENEMY_SPAWN_INTERVAL == 0:
            spawn_msg = try_spawn_enemy(grid, player, enemies, items)
            if spawn_msg:
                message = (message + '  ' + spawn_msg).strip() if message else spawn_msg

        # ===== [6c] ボス出現（SURVIVE_TURNS - BOSS_SPAWN_OFFSET ターンで1度だけ）=====
        if turn == SURVIVE_TURNS - BOSS_SPAWN_OFFSET and not boss_spawned:
            boss_spawned = True
            boss_msg = try_spawn_boss(grid, player, enemies, items)
            if boss_msg:
                message = (message + '  ' + boss_msg).strip() if message else boss_msg

        # ===== [7] 勝敗判定（仕様 §7.1 [7]: 生存型クリアの主要判定タイミング）=====
        outcome = check_outcome(player, turn)
        if outcome:
            state = outcome


if __name__ == '__main__':
    main()
