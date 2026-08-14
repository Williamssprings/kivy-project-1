"""
NC 工具箱 - Android APK 完整版
包含：竖向补偿 / 横向补偿 / 坐标补齐 / 按段拆分 / 按段合并
所有核心逻辑完整内置，无需额外导入。
"""

import re
import os
import sys
from collections import defaultdict

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.gridlayout import GridLayout
from kivy.clock import Clock

# Android 文件选择器 (plyer)
try:
    from plyer import filechooser
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False
    print("警告: plyer 未安装，文件选择功能不可用")


# =====================================================================
# 1. 竖向补偿（竖放腰形，Y轴判断）
# =====================================================================
def process_vertical_comp(input_path, output_path, comp_count, macro_nums,
                          tangent_rb, tangent_rt, tangent_lt, tangent_lb,
                          auto_insert=True, log_callback=print):
    """竖向补偿核心，参数与之前完全一致"""
    EDGE_TOLERANCE = 0.05
    RATIO_DECIMALS = 3
    MACRO_NUMBERS = macro_nums
    COMPENSATION_COUNT = comp_count
    TANGENT_RIGHT_BOTTOM_Y = tangent_rb
    TANGENT_RIGHT_TOP_Y = tangent_rt
    TANGENT_LEFT_TOP_Y = tangent_lt
    TANGENT_LEFT_BOTTOM_Y = tangent_lb
    AUTO_INSERT_MIDPOINT = auto_insert

    def analyze_all_points(lines):
        g_pattern = re.compile(r'G(\d+)', re.IGNORECASE)
        y_pattern = re.compile(r'Y(-?\d*\.?\d+)', re.IGNORECASE)
        x_pattern = re.compile(r'X(-?\d*\.?\d+)', re.IGNORECASE)
        current_modal = None
        points = []
        for i, line in enumerate(lines):
            clean = line.strip()
            g_matches = g_pattern.findall(clean)
            for g in g_matches:
                g_num = int(g)
                if g_num in [0, 1, 2, 3]:
                    current_modal = g_num
            if current_modal == 1:
                x_match = x_pattern.search(clean)
                y_match = y_pattern.search(clean)
                if x_match and y_match:
                    points.append((i + 1, float(x_match.group(1)), float(y_match.group(1)), clean))
        return points

    def find_continuous_segment(pts_with_idx, axis='y'):
        if not pts_with_idx:
            return []
        sorted_pts = sorted(pts_with_idx, key=lambda x: x[0])
        segments = []
        current_seg = [sorted_pts[0]]
        for i in range(1, len(sorted_pts)):
            if sorted_pts[i][0] == sorted_pts[i-1][0] + 1:
                current_seg.append(sorted_pts[i])
            else:
                segments.append(current_seg)
                current_seg = [sorted_pts[i]]
        segments.append(current_seg)
        if axis == 'y':
            best_seg = max(segments, key=lambda seg: max(p[1][2] for p in seg) - min(p[1][2] for p in seg))
        else:
            best_seg = max(segments, key=lambda seg: max(p[1][1] for p in seg) - min(p[1][1] for p in seg))
        return best_seg

    def insert_midpoints(lines):
        n_pattern = re.compile(r'^N(\d+)', re.IGNORECASE)
        n_segments = []
        for i, line in enumerate(lines):
            match = n_pattern.match(line.strip())
            if match:
                n_segments.append((i, match.group(1)))
        if not n_segments:
            return lines
        insertions = []
        for seg_idx, (start_idx, n_num) in enumerate(n_segments):
            end_idx = n_segments[seg_idx + 1][0] if seg_idx + 1 < len(n_segments) else len(lines)
            points = analyze_all_points(lines[start_idx:end_idx])
            if not points:
                continue
            x_vals = [p[1] for p in points]
            x_max = max(x_vals)
            x_min = min(x_vals)
            right_candidates = [(i, p) for i, p in enumerate(points) if abs(p[1] - x_max) < EDGE_TOLERANCE]
            right_seg = find_continuous_segment(right_candidates, 'y')
            if len(right_seg) == 2:
                start_pt = right_seg[0][1]
                end_pt = right_seg[1][1]
                mid_y = (start_pt[2] + end_pt[2]) / 2
                orig_line = start_pt[3]
                new_line = re.sub(r'Y-?\d*\.?\d+', f'Y{mid_y:.3f}', orig_line, flags=re.IGNORECASE)
                insert_idx = start_idx + end_pt[0]
                insertions.append((insert_idx, new_line))
                log_callback(f'  N{n_num} 段: 右直边插入中点 Y={mid_y:.3f}')
            left_candidates = [(i, p) for i, p in enumerate(points) if abs(p[1] - x_min) < EDGE_TOLERANCE]
            left_seg = find_continuous_segment(left_candidates, 'y')
            if len(left_seg) == 2:
                start_pt = left_seg[0][1]
                end_pt = left_seg[1][1]
                mid_y = (start_pt[2] + end_pt[2]) / 2
                orig_line = start_pt[3]
                new_line = re.sub(r'Y-?\d*\.?\d+', f'Y{mid_y:.3f}', orig_line, flags=re.IGNORECASE)
                insert_idx = start_idx + end_pt[0]
                insertions.append((insert_idx, new_line))
                log_callback(f'  N{n_num} 段: 左直边插入中点 Y={mid_y:.3f}')
        insertions.sort(key=lambda x: x[0], reverse=True)
        for idx, new_line in insertions:
            lines.insert(idx, new_line + '\n')
        return lines

    def detect_contour_params(points):
        x_vals = [p[1] for p in points]
        y_vals = [p[2] for p in points]
        x_max = max(x_vals)
        x_min = min(x_vals)
        y_max = max(y_vals)
        y_min = min(y_vals)
        top_idx = y_vals.index(y_max)
        top_x = points[top_idx][1]
        bottom_idx = y_vals.index(y_min)
        bottom_x = points[bottom_idx][1]
        right_candidates = [(i, p) for i, p in enumerate(points) if abs(p[1] - x_max) < EDGE_TOLERANCE]
        right_seg = find_continuous_segment(right_candidates, 'y')
        left_candidates = [(i, p) for i, p in enumerate(points) if abs(p[1] - x_min) < EDGE_TOLERANCE]
        left_seg = find_continuous_segment(left_candidates, 'y')
        if right_seg:
            right_top_y = max(p[1][2] for p in right_seg)
            right_bottom_y = min(p[1][2] for p in right_seg)
            right_mid_y = (right_top_y + right_bottom_y) / 2
        else:
            right_mid_y = (y_max + y_min) / 2
        if left_seg:
            left_top_y = max(p[1][2] for p in left_seg)
            left_bottom_y = min(p[1][2] for p in left_seg)
            left_mid_y = (left_top_y + left_bottom_y) / 2
        else:
            left_mid_y = (y_max + y_min) / 2
        right_bottom_tan_y = TANGENT_RIGHT_BOTTOM_Y if TANGENT_RIGHT_BOTTOM_Y is not None else (right_bottom_y if right_seg else y_min + (y_max - y_min) * 0.2)
        right_top_tan_y = TANGENT_RIGHT_TOP_Y if TANGENT_RIGHT_TOP_Y is not None else (right_top_y if right_seg else y_min + (y_max - y_min) * 0.8)
        left_top_tan_y = TANGENT_LEFT_TOP_Y if TANGENT_LEFT_TOP_Y is not None else (left_top_y if left_seg else y_min + (y_max - y_min) * 0.8)
        left_bottom_tan_y = TANGENT_LEFT_BOTTOM_Y if TANGENT_LEFT_BOTTOM_Y is not None else (left_bottom_y if left_seg else y_min + (y_max - y_min) * 0.2)
        return {
            'x_max': x_max, 'x_min': x_min, 'y_max': y_max, 'y_min': y_min,
            'top_x': top_x, 'bottom_x': bottom_x,
            'right_mid_y': right_mid_y, 'left_mid_y': left_mid_y,
            'right_bottom_tan_y': right_bottom_tan_y, 'right_top_tan_y': right_top_tan_y,
            'left_top_tan_y': left_top_tan_y, 'left_bottom_tan_y': left_bottom_tan_y,
        }

    def determine_interval(x, y, params):
        x_max = params['x_max']; x_min = params['x_min']
        y_max = params['y_max']; y_min = params['y_min']
        top_x = params['top_x']; bottom_x = params['bottom_x']
        right_mid_y = params['right_mid_y']; left_mid_y = params['left_mid_y']
        right_bottom_tan = params['right_bottom_tan_y']; right_top_tan = params['right_top_tan_y']
        left_top_tan = params['left_top_tan_y']; left_bottom_tan = params['left_bottom_tan_y']
        is_right_edge = abs(x - x_max) < EDGE_TOLERANCE
        is_left_edge = abs(x - x_min) < EDGE_TOLERANCE
        is_top_arc = y > right_top_tan and y > left_top_tan
        is_bottom_arc = y < right_bottom_tan and y < left_bottom_tan
        center_x = (top_x + bottom_x) / 2
        if COMPENSATION_COUNT == 4:
            is_right_side = x >= center_x
            if is_right_side:
                if y < right_mid_y: return (0, 1, y_min, right_mid_y)
                else: return (1, 2, right_mid_y, y_max)
            else:
                if y > left_mid_y: return (2, 3, y_max, left_mid_y)
                else: return (3, 0, left_mid_y, y_min)
        if is_right_edge:
            if y <= right_bottom_tan: return (0, 1, y_min, right_bottom_tan)
            elif y <= right_mid_y: return (1, 2, right_bottom_tan, right_mid_y)
            elif y <= right_top_tan: return (2, 3, right_mid_y, right_top_tan)
            else: return (3, 4, right_top_tan, y_max)
        if is_left_edge:
            if y >= left_top_tan: return (4, 5, y_max, left_top_tan)
            elif y >= left_mid_y: return (5, 6, left_top_tan, left_mid_y)
            elif y >= left_bottom_tan: return (6, 7, left_mid_y, left_bottom_tan)
            else: return (7, 0, left_bottom_tan, y_min)
        if is_top_arc:
            if x >= top_x: return (3, 4, right_top_tan, y_max)
            else: return (4, 5, y_max, left_top_tan)
        if is_bottom_arc:
            if x <= bottom_x: return (7, 0, left_bottom_tan, y_min)
            else: return (0, 1, y_min, right_bottom_tan)
        mid_y = (y_max + y_min) / 2
        if y > mid_y:
            if x > top_x: return (3, 4, right_top_tan, y_max)
            else: return (4, 5, y_max, left_top_tan)
        else:
            if x < bottom_x: return (7, 0, left_bottom_tan, y_min)
            else: return (0, 1, y_min, right_bottom_tan)

    def replace_z_with_compensation(code, z_orig_str, start_macro, end_macro, ratio):
        z_pattern = re.compile(r'Z(-?\d*\.?\d+)', re.IGNORECASE)
        match = z_pattern.search(code)
        if not match: return code
        ratio_str = f'{ratio:.{RATIO_DECIMALS}f}'.rstrip('0').rstrip('.')
        new_z = f'Z[{z_orig_str}+[#{start_macro}+[#{end_macro}-#{start_macro}]*{ratio_str}]]'
        return code[:match.start()] + new_z + code[match.end():]

    # 主流程
    try:
        log_callback(f"正在处理: {os.path.basename(input_path)}")
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        log_callback(f"❌ 读取文件失败: {e}")
        return False

    if AUTO_INSERT_MIDPOINT:
        log_callback("检查直边中点...")
        lines = insert_midpoints(lines)

    output_lines = lines.copy()
    all_points = analyze_all_points(lines)
    if not all_points:
        log_callback("错误：未找到G01点")
        return False

    params = detect_contour_params(all_points)
    log_callback("\n===== 轮廓参数 =====")
    log_callback(f"X范围: {params['x_min']:.4f} ~ {params['x_max']:.4f}")
    log_callback(f"Y范围: {params['y_min']:.4f} ~ {params['y_max']:.4f}")
    log_callback(f"相切点Y (右下,右上,左上,左下): {params['right_bottom_tan_y']:.3f}, {params['right_top_tan_y']:.3f}, {params['left_top_tan_y']:.3f}, {params['left_bottom_tan_y']:.3f}")

    z_pattern = re.compile(r'Z(-?\d*\.?\d+)', re.IGNORECASE)
    total_replaced = 0
    for line_num, x, y, code in all_points:
        start_idx, end_idx, start_y, end_y = determine_interval(x, y, params)
        ratio = 0.0 if abs(end_y - start_y) < 1e-9 else (y - start_y) / (end_y - start_y)
        ratio = max(0.0, min(1.0, ratio))
        z_match = z_pattern.search(code)
        if not z_match: continue
        z_orig_str = z_match.group(1)
        new_code = replace_z_with_compensation(code, z_orig_str, MACRO_NUMBERS[start_idx], MACRO_NUMBERS[end_idx], ratio)
        output_lines[line_num - 1] = new_code + '\n'
        total_replaced += 1

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)
        log_callback(f"✅ 处理完成！替换Z值行数: {total_replaced}")
        return True
    except Exception as e:
        log_callback(f"❌ 写入文件失败: {e}")
        return False


# =====================================================================
# 2. 横向补偿（横放腰形，X轴判断）
# =====================================================================
def process_horizontal_comp(input_path, output_path, comp_count, macro_nums,
                            tangent_bl, tangent_br, tangent_tr, tangent_tl,
                            auto_insert=True, log_callback=print):
    EDGE_TOLERANCE = 0.02
    RATIO_DECIMALS = 3
    MACRO_NUMBERS = macro_nums
    COMPENSATION_COUNT = comp_count
    TANGENT_BOTTOM_LEFT_X = tangent_bl
    TANGENT_BOTTOM_RIGHT_X = tangent_br
    TANGENT_TOP_RIGHT_X = tangent_tr
    TANGENT_TOP_LEFT_X = tangent_tl
    AUTO_INSERT_MIDPOINT = auto_insert

    def analyze_all_points(lines):
        g_pattern = re.compile(r'G(\d+)', re.IGNORECASE)
        y_pattern = re.compile(r'Y(-?\d*\.?\d+)', re.IGNORECASE)
        x_pattern = re.compile(r'X(-?\d*\.?\d+)', re.IGNORECASE)
        current_modal = None
        points = []
        for i, line in enumerate(lines):
            clean = line.strip()
            g_matches = g_pattern.findall(clean)
            for g in g_matches:
                g_num = int(g)
                if g_num in [0, 1, 2, 3]:
                    current_modal = g_num
            if current_modal == 1:
                x_match = x_pattern.search(clean)
                y_match = y_pattern.search(clean)
                if x_match and y_match:
                    points.append((i + 1, float(x_match.group(1)), float(y_match.group(1)), clean))
        return points

    def find_continuous_segment(pts_with_idx, axis='x'):
        if not pts_with_idx:
            return []
        sorted_pts = sorted(pts_with_idx, key=lambda x: x[0])
        segments = []
        current_seg = [sorted_pts[0]]
        for i in range(1, len(sorted_pts)):
            if sorted_pts[i][0] == sorted_pts[i-1][0] + 1:
                current_seg.append(sorted_pts[i])
            else:
                segments.append(current_seg)
                current_seg = [sorted_pts[i]]
        segments.append(current_seg)
        if axis == 'x':
            best_seg = max(segments, key=lambda seg: max(p[1][1] for p in seg) - min(p[1][1] for p in seg))
        else:
            best_seg = max(segments, key=lambda seg: max(p[1][2] for p in seg) - min(p[1][2] for p in seg))
        return best_seg

    def insert_midpoints(lines):
        n_pattern = re.compile(r'^N(\d+)', re.IGNORECASE)
        n_segments = []
        for i, line in enumerate(lines):
            match = n_pattern.match(line.strip())
            if match:
                n_segments.append((i, match.group(1)))
        if not n_segments:
            return lines
        insertions = []
        for seg_idx, (start_idx, n_num) in enumerate(n_segments):
            end_idx = n_segments[seg_idx + 1][0] if seg_idx + 1 < len(n_segments) else len(lines)
            points = analyze_all_points(lines[start_idx:end_idx])
            if not points:
                continue
            y_vals = [p[2] for p in points]
            y_max = max(y_vals)
            y_min = min(y_vals)
            bottom_candidates = [(i, p) for i, p in enumerate(points) if abs(p[2] - y_min) < EDGE_TOLERANCE]
            bottom_seg = find_continuous_segment(bottom_candidates, 'x')
            if len(bottom_seg) == 2:
                start_pt = bottom_seg[0][1]
                end_pt = bottom_seg[1][1]
                mid_x = (start_pt[1] + end_pt[1]) / 2
                orig_line = start_pt[3]
                new_line = re.sub(r'X-?\d*\.?\d+', f'X{mid_x:.3f}', orig_line, flags=re.IGNORECASE)
                insert_idx = start_idx + end_pt[0]
                insertions.append((insert_idx, new_line))
                log_callback(f'  N{n_num} 段: 下直边插入中点 X={mid_x:.3f}')
            top_candidates = [(i, p) for i, p in enumerate(points) if abs(p[2] - y_max) < EDGE_TOLERANCE]
            top_seg = find_continuous_segment(top_candidates, 'x')
            if len(top_seg) == 2:
                start_pt = top_seg[0][1]
                end_pt = top_seg[1][1]
                mid_x = (start_pt[1] + end_pt[1]) / 2
                orig_line = start_pt[3]
                new_line = re.sub(r'X-?\d*\.?\d+', f'X{mid_x:.3f}', orig_line, flags=re.IGNORECASE)
                insert_idx = start_idx + end_pt[0]
                insertions.append((insert_idx, new_line))
                log_callback(f'  N{n_num} 段: 上直边插入中点 X={mid_x:.3f}')
        insertions.sort(key=lambda x: x[0], reverse=True)
        for idx, new_line in insertions:
            lines.insert(idx, new_line + '\n')
        return lines

    def detect_contour_params(points):
        x_vals = [p[1] for p in points]
        y_vals = [p[2] for p in points]
        x_max = max(x_vals)
        x_min = min(x_vals)
        y_max = max(y_vals)
        y_min = min(y_vals)
        right_idx = x_vals.index(x_max)
        right_y = points[right_idx][2]
        left_idx = x_vals.index(x_min)
        left_y = points[left_idx][2]
        bottom_candidates = [(i, p) for i, p in enumerate(points) if abs(p[2] - y_min) < EDGE_TOLERANCE]
        bottom_seg = find_continuous_segment(bottom_candidates, 'x')
        top_candidates = [(i, p) for i, p in enumerate(points) if abs(p[2] - y_max) < EDGE_TOLERANCE]
        top_seg = find_continuous_segment(top_candidates, 'x')
        if bottom_seg:
            bottom_left_x = min(p[1][1] for p in bottom_seg)
            bottom_right_x = max(p[1][1] for p in bottom_seg)
            bottom_mid_x = (bottom_left_x + bottom_right_x) / 2
        else:
            bottom_mid_x = (x_max + x_min) / 2
        if top_seg:
            top_left_x = min(p[1][1] for p in top_seg)
            top_right_x = max(p[1][1] for p in top_seg)
            top_mid_x = (top_left_x + top_right_x) / 2
        else:
            top_mid_x = (x_max + x_min) / 2
        bottom_left_tan_x = TANGENT_BOTTOM_LEFT_X if TANGENT_BOTTOM_LEFT_X is not None else (bottom_left_x if bottom_seg else x_min + (x_max - x_min) * 0.2)
        bottom_right_tan_x = TANGENT_BOTTOM_RIGHT_X if TANGENT_BOTTOM_RIGHT_X is not None else (bottom_right_x if bottom_seg else x_min + (x_max - x_min) * 0.8)
        top_right_tan_x = TANGENT_TOP_RIGHT_X if TANGENT_TOP_RIGHT_X is not None else (top_right_x if top_seg else x_min + (x_max - x_min) * 0.8)
        top_left_tan_x = TANGENT_TOP_LEFT_X if TANGENT_TOP_LEFT_X is not None else (top_left_x if top_seg else x_min + (x_max - x_min) * 0.2)
        return {
            'x_max': x_max, 'x_min': x_min, 'y_max': y_max, 'y_min': y_min,
            'right_y': right_y, 'left_y': left_y,
            'bottom_mid_x': bottom_mid_x, 'top_mid_x': top_mid_x,
            'bottom_left_tan_x': bottom_left_tan_x, 'bottom_right_tan_x': bottom_right_tan_x,
            'top_right_tan_x': top_right_tan_x, 'top_left_tan_x': top_left_tan_x,
        }

    def determine_interval(x, y, params):
        x_max = params['x_max']; x_min = params['x_min']
        y_max = params['y_max']; y_min = params['y_min']
        right_y = params['right_y']; left_y = params['left_y']
        bottom_mid_x = params['bottom_mid_x']; top_mid_x = params['top_mid_x']
        bottom_left_tan = params['bottom_left_tan_x']; bottom_right_tan = params['bottom_right_tan_x']
        top_right_tan = params['top_right_tan_x']; top_left_tan = params['top_left_tan_x']
        is_bottom_edge = abs(y - y_min) < EDGE_TOLERANCE
        is_top_edge = abs(y - y_max) < EDGE_TOLERANCE
        is_left_arc = x < bottom_left_tan and x < top_left_tan
        is_right_arc = x > bottom_right_tan and x > top_right_tan
        center_y = (right_y + left_y) / 2
        if COMPENSATION_COUNT == 4:
            is_bottom_side = y <= center_y
            if is_bottom_side:
                if x < bottom_mid_x: return (0, 1, x_min, bottom_mid_x)
                else: return (1, 2, bottom_mid_x, x_max)
            else:
                if x > top_mid_x: return (2, 3, x_max, top_mid_x)
                else: return (3, 0, top_mid_x, x_min)
        if is_bottom_edge:
            if x <= bottom_left_tan: return (0, 1, x_min, bottom_left_tan)
            elif x <= bottom_mid_x: return (1, 2, bottom_left_tan, bottom_mid_x)
            elif x <= bottom_right_tan: return (2, 3, bottom_mid_x, bottom_right_tan)
            else: return (3, 4, bottom_right_tan, x_max)
        if is_top_edge:
            if x >= top_right_tan: return (4, 5, x_max, top_right_tan)
            elif x >= top_mid_x: return (5, 6, top_right_tan, top_mid_x)
            elif x >= top_left_tan: return (6, 7, top_mid_x, top_left_tan)
            else: return (7, 0, top_left_tan, x_min)
        if is_left_arc:
            if y <= left_y: return (0, 1, x_min, bottom_left_tan)
            else: return (7, 0, top_left_tan, x_min)
        if is_right_arc:
            if y >= right_y: return (4, 5, x_max, top_right_tan)
            else: return (3, 4, bottom_right_tan, x_max)
        mid_x = (x_max + x_min) / 2
        if x < mid_x:
            if y <= center_y: return (0, 1, x_min, bottom_left_tan)
            else: return (7, 0, top_left_tan, x_min)
        else:
            if y >= center_y: return (4, 5, x_max, top_right_tan)
            else: return (3, 4, bottom_right_tan, x_max)

    def replace_z_with_compensation(code, z_orig_str, start_macro, end_macro, ratio):
        z_pattern = re.compile(r'Z(-?\d*\.?\d+)', re.IGNORECASE)
        match = z_pattern.search(code)
        if not match: return code
        ratio_str = f'{ratio:.{RATIO_DECIMALS}f}'.rstrip('0').rstrip('.')
        new_z = f'Z[{z_orig_str}+[#{start_macro}+[#{end_macro}-#{start_macro}]*{ratio_str}]]'
        return code[:match.start()] + new_z + code[match.end():]

    try:
        log_callback(f"正在处理: {os.path.basename(input_path)}")
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        log_callback(f"❌ 读取文件失败: {e}")
        return False

    if AUTO_INSERT_MIDPOINT:
        log_callback("检查直边中点...")
        lines = insert_midpoints(lines)

    output_lines = lines.copy()
    all_points = analyze_all_points(lines)
    if not all_points:
        log_callback("错误：未找到G01点")
        return False

    params = detect_contour_params(all_points)
    log_callback("\n===== 轮廓参数 =====")
    log_callback(f"X范围: {params['x_min']:.4f} ~ {params['x_max']:.4f}")
    log_callback(f"Y范围: {params['y_min']:.4f} ~ {params['y_max']:.4f}")
    log_callback(f"相切点X (左下,右下,右上,左上): {params['bottom_left_tan_x']:.3f}, {params['bottom_right_tan_x']:.3f}, {params['top_right_tan_x']:.3f}, {params['top_left_tan_x']:.3f}")

    z_pattern = re.compile(r'Z(-?\d*\.?\d+)', re.IGNORECASE)
    total_replaced = 0
    for line_num, x, y, code in all_points:
        start_idx, end_idx, start_x, end_x = determine_interval(x, y, params)
        ratio = 0.0 if abs(end_x - start_x) < 1e-9 else (x - start_x) / (end_x - start_x)
        ratio = max(0.0, min(1.0, ratio))
        z_match = z_pattern.search(code)
        if not z_match: continue
        z_orig_str = z_match.group(1)
        new_code = replace_z_with_compensation(code, z_orig_str, MACRO_NUMBERS[start_idx], MACRO_NUMBERS[end_idx], ratio)
        output_lines[line_num - 1] = new_code + '\n'
        total_replaced += 1

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)
        log_callback(f"✅ 处理完成！替换Z值行数: {total_replaced}")
        return True
    except Exception as e:
        log_callback(f"❌ 写入文件失败: {e}")
        return False


# =====================================================================
# 3. 坐标补齐
# =====================================================================
def process_fill_coord(input_path, output_path, log_callback=print):
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        log_callback(f"❌ 读取文件失败: {e}")
        return False

    last_x = last_y = last_z = None
    output_lines = []
    current_motion_mode = "CUT"
    non_motion_g_pattern = re.compile(r'G(68|52|92|10)(\.\d+)?(?![0-9.])', re.IGNORECASE)
    g00_pattern = re.compile(r'G(00|0)\b', re.IGNORECASE)
    cut_g_pattern = re.compile(r'G(01|1|02|2|03|3)\b', re.IGNORECASE)
    coord_pattern = r'([+-]?(?:\d+\.?\d*|\.\d+))'

    processed_count = 0
    for line in lines:
        original = line.rstrip('\n\r')
        stripped = original.strip()
        if not stripped or stripped == '%' or stripped.startswith('('):
            output_lines.append(original)
            continue

        comment = ''
        code_part = original
        comment_match = re.search(r'\(.*\)', original)
        if comment_match:
            comment = comment_match.group(0)
            code_part = original[:comment_match.start()] + original[comment_match.end():]

        if non_motion_g_pattern.search(code_part):
            output_lines.append(original)
            continue

        x_match = re.search(r'X' + coord_pattern, code_part, re.IGNORECASE)
        y_match = re.search(r'Y' + coord_pattern, code_part, re.IGNORECASE)
        z_match = re.search(r'Z' + coord_pattern, code_part, re.IGNORECASE)
        has_x = x_match is not None
        has_y = y_match is not None
        has_z = z_match is not None

        if not has_x and not has_y and not has_z:
            output_lines.append(original)
            continue

        if g00_pattern.search(code_part):
            current_motion_mode = "RAPID"
        elif cut_g_pattern.search(code_part):
            current_motion_mode = "CUT"

        if has_x: last_x = x_match.group(1)
        if has_y: last_y = y_match.group(1)
        if has_z: last_z = z_match.group(1)

        if current_motion_mode == "RAPID":
            output_lines.append(original)
            continue

        if last_x is None or last_y is None or last_z is None:
            output_lines.append(original)
            continue

        new_code = re.sub(r'[XYZ]' + coord_pattern, '', code_part, flags=re.IGNORECASE)
        new_code = re.sub(r'  +', ' ', new_code)
        coord_str = f"X{last_x} Y{last_y} Z{last_z}"

        g_insert_match = re.search(r'(G(?:01|1|02|2|03|3)\b)', new_code, re.IGNORECASE)
        if g_insert_match:
            insert_pos = g_insert_match.end()
            new_code = new_code[:insert_pos] + ' ' + coord_str + new_code[insert_pos:]
        else:
            leading_len = len(code_part) - len(code_part.lstrip())
            leading = ' ' * leading_len
            rest = new_code.strip()
            new_code = leading + coord_str + (' ' + rest if rest else '')

        new_code = re.sub(r'  +', ' ', new_code)
        if comment:
            new_code = new_code.rstrip() + ' ' + comment
        output_lines.append(new_code)
        processed_count += 1

    try:
        with open(output_path, 'w', encoding='utf-8', newline='\n') as f:
            for line in output_lines:
                f.write(line + '\n')
        log_callback(f"✅ 处理完成！共补齐 {processed_count} 行")
        return True
    except Exception as e:
        log_callback(f"❌ 写入文件失败: {e}")
        return False


# =====================================================================
# 4. 按段拆分
# =====================================================================
def process_split(input_path, output_dir, log_callback=print):
    try:
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        log_callback(f"❌ 读取文件失败: {e}")
        return False

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    n_pattern = re.compile(r'^N(\d+)', re.IGNORECASE)
    segments = []
    for i, line in enumerate(lines):
        match = n_pattern.match(line.strip())
        if match:
            n_num = int(match.group(1))
            segments.append((n_num, i))

    if not segments:
        log_callback("❌ 未找到任何N段标识")
        return False

    log_callback(f"===== 识别到 {len(segments)} 个N段 =====")
    for n_num, start_line in segments:
        log_callback(f"  N{n_num}: 起始行 {start_line + 1}")

    if not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            log_callback(f"📁 创建输出目录: {output_dir}")
        except Exception as e:
            log_callback(f"❌ 创建目录失败: {e}")
            return False

    for seg_idx, (n_num, start_line) in enumerate(segments):
        end_line = segments[seg_idx + 1][1] if seg_idx + 1 < len(segments) else len(lines)
        segment_lines = lines[start_line:end_line]
        output_filename = f'{base_name}-N{n_num}.NC'
        output_path = os.path.join(output_dir, output_filename)
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.writelines(segment_lines)
            log_callback(f"✅ N{n_num} 段已保存: {output_filename} (行数: {len(segment_lines)})")
        except Exception as e:
            log_callback(f"❌ 写入文件失败: {e}")
            return False

    log_callback(f"\n===== 拆分完成，共 {len(segments)} 个文件 =====")
    return True


# =====================================================================
# 5. 按段合并
# =====================================================================
def process_merge(input_dir, output_dir, log_callback=print):
    try:
        if not os.path.exists(input_dir):
            log_callback(f"❌ 输入文件夹不存在: {input_dir}")
            return False
    except Exception as e:
        log_callback(f"❌ 访问输入文件夹失败: {e}")
        return False

    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            log_callback(f"📁 创建输出目录: {output_dir}")
    except Exception as e:
        log_callback(f"❌ 创建输出目录失败: {e}")
        return False

    filename_pattern = re.compile(r'^(O\d+)-N(\d+)\.NC$', re.IGNORECASE)
    programs = defaultdict(dict)

    log_callback(f"===== 扫描文件夹: {input_dir} =====")
    for filename in os.listdir(input_dir):
        if not filename.lower().endswith('.nc'):
            continue
        match = filename_pattern.match(filename)
        if match:
            program_name = match.group(1).upper()
            n_num = int(match.group(2))
            programs[program_name][n_num] = filename
            log_callback(f"  找到: {filename} -> 程序 {program_name}, 第 {n_num} 段")

    if not programs:
        log_callback("❌ 未找到任何N段文件（文件名格式需为 Oxxxx-Ny.NC）")
        return False

    log_callback(f"\n===== 识别到 {len(programs)} 个程序 =====")
    merged_count = 0
    for program_name in sorted(programs.keys()):
        segments = programs[program_name]
        segment_nums = sorted(segments.keys())
        log_callback(f"\n----- {program_name} -----")
        log_callback(f"  包含 {len(segment_nums)} 段: N{', N'.join(str(n) for n in segment_nums)}")

        merged_lines = []
        for n_num in segment_nums:
            filename = segments[n_num]
            filepath = os.path.join(input_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
                merged_lines.extend(lines)
                log_callback(f"  N{n_num}: {len(lines)} 行")
            except Exception as e:
                log_callback(f"  ❌ 读取 {filename} 失败: {e}")
                return False

        output_filename = f'{program_name}合并.NC'
        output_path = os.path.join(output_dir, output_filename)
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.writelines(merged_lines)
            log_callback(f"  ✅ 合并完成: {output_filename} (总行数: {len(merged_lines)})")
            merged_count += 1
        except Exception as e:
            log_callback(f"  ❌ 写入 {output_filename} 失败: {e}")
            return False

    log_callback(f"\n===== 全部完成，共合并 {merged_count} 个程序 =====")
    return True


# =====================================================================
# Kivy 界面
# =====================================================================
class NTToolLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation='vertical', spacing=10, padding=10, **kwargs)

        # 标题
        self.add_widget(Label(text="NC 工具箱 v1.0 (安卓版)", size_hint_y=0.08, font_size='18sp'))

        # 功能选择
        top_box = BoxLayout(size_hint_y=0.08, spacing=10)
        top_box.add_widget(Label(text="选择功能:", size_hint_x=0.25))
        self.func_spinner = Spinner(
            text='竖向补偿',
            values=('竖向补偿', '横向补偿', '坐标补齐', '按段拆分', '按段合并'),
            size_hint_x=0.75
        )
        self.func_spinner.bind(text=self.on_func_change)
        top_box.add_widget(self.func_spinner)
        self.add_widget(top_box)

        # 参数区域 (滚动)
        scroll = ScrollView()
        self.param_layout = GridLayout(cols=2, spacing=8, size_hint_y=None)
        self.param_layout.bind(minimum_height=self.param_layout.setter('height'))
        scroll.add_widget(self.param_layout)
        self.add_widget(scroll)

        # 日志区域
        log_box = BoxLayout(orientation='vertical', size_hint_y=0.4)
        log_box.add_widget(Label(text="运行日志:", size_hint_y=0.15))
        self.log_text = TextInput(text='', readonly=True, background_color=[0.9, 0.9, 0.9, 1])
        log_box.add_widget(self.log_text)
        self.add_widget(log_box)

        # 底部按钮
        btn_box = BoxLayout(size_hint_y=0.08, spacing=10)
        btn_box.add_widget(Button(text="选择文件/文件夹", on_press=self.pick_file))
        btn_box.add_widget(Button(text="开始处理", on_press=self.run_process))
        btn_box.add_widget(Button(text="清空日志", on_press=self.clear_log))
        self.add_widget(btn_box)

        # 存储参数控件
        self.param_widgets = []
        # 初始化界面
        self.on_func_change(self.func_spinner, self.func_spinner.text)

    def on_func_change(self, spinner, text):
        """切换功能时重建参数输入框"""
        self.param_layout.clear_widgets()
        self.param_widgets = []
        func_map = {
            '竖向补偿': self.build_vertical_ui,
            '横向补偿': self.build_horizontal_ui,
            '坐标补齐': self.build_fill_ui,
            '按段拆分': self.build_split_ui,
            '按段合并': self.build_merge_ui,
        }
        if text in func_map:
            func_map[text]()

    def add_label_entry(self, label_text, default="", hint=""):
        self.param_layout.add_widget(Label(text=label_text, size_hint_y=None, height=30))
        inp = TextInput(text=default, hint_text=hint, multiline=False, size_hint_y=None, height=30)
        self.param_layout.add_widget(inp)
        self.param_widgets.append(inp)
        return inp

    def build_vertical_ui(self):
        self.add_label_entry("输入文件路径:", "/sdcard/Download/", "点下方选择文件")
        self.add_label_entry("输出文件路径:", "/sdcard/Download/out.NC")
        self.add_label_entry("补偿点数 (4或8):", "8")
        self.add_label_entry("宏变量 (逗号分隔):", "753,754,755,756,757,758,759,760")
        self.add_label_entry("右下相切Y (空=自动):", "")
        self.add_label_entry("右上相切Y (空=自动):", "")
        self.add_label_entry("左上相切Y (空=自动):", "")
        self.add_label_entry("左下相切Y (空=自动):", "")

    def build_horizontal_ui(self):
        self.add_label_entry("输入文件路径:", "/sdcard/Download/")
        self.add_label_entry("输出文件路径:", "/sdcard/Download/out.NC")
        self.add_label_entry("补偿点数 (4或8):", "8")
        self.add_label_entry("宏变量 (逗号分隔):", "1,2,3,4,5,6,7,8")
        self.add_label_entry("左下相切X (空=自动):", "")
        self.add_label_entry("右下相切X (空=自动):", "")
        self.add_label_entry("右上相切X (空=自动):", "")
        self.add_label_entry("左上相切X (空=自动):", "")

    def build_fill_ui(self):
        self.add_label_entry("输入文件路径:", "/sdcard/Download/")
        self.add_label_entry("输出文件路径:", "/sdcard/Download/filled.NC")

    def build_split_ui(self):
        self.add_label_entry("输入文件路径:", "/sdcard/Download/")
        self.add_label_entry("输出目录 (留空=同目录):", "")

    def build_merge_ui(self):
        self.add_label_entry("输入文件夹 (含N段文件):", "/sdcard/Download/")
        self.add_label_entry("输出文件夹 (留空=同目录):", "")

    def pick_file(self, *args):
        if not HAS_PLYER:
            self.log("错误: 文件选择器不可用，请手动输入路径")
            return
        func = self.func_spinner.text
        if func in ('按段合并',):
            filechooser.choose_dir(on_selection=self.on_dir_selected)
        else:
            filechooser.choose_file(on_selection=self.on_file_selected)

    def on_file_selected(self, selection):
        if selection and self.param_widgets:
            self.param_widgets[0].text = selection[0]
            self.log(f"已选文件: {selection[0]}")

    def on_dir_selected(self, selection):
        if selection and self.param_widgets:
            self.param_widgets[0].text = selection[0]
            self.log(f"已选文件夹: {selection[0]}")

    def clear_log(self, *args):
        self.log_text.text = ""

    def log(self, msg):
        self.log_text.text += msg + "\n"
        self.log_text.cursor = (0, len(self.log_text.text))

    def run_process(self, *args):
        func = self.func_spinner.text
        vals = [w.text.strip() for w in self.param_widgets]

        if not vals or not vals[0]:
            self.log("❌ 请先选择输入文件/文件夹")
            return

        def log_cb(msg):
            Clock.schedule_once(lambda dt: self.log(msg))

        self.log(f"开始执行: {func}")

        try:
            if func == '竖向补偿':
                if len(vals) < 8:
                    self.log("参数不足")
                    return
                macro_list = [int(x.strip()) for x in vals[2].split(',') if x.strip()]
                comp_count = int(vals[1])
                success = process_vertical_comp(
                    vals[0], vals[1], comp_count, macro_list,
                    float(vals[3]) if vals[3] else None,
                    float(vals[4]) if vals[4] else None,
                    float(vals[5]) if vals[5] else None,
                    float(vals[6]) if vals[6] else None,
                    log_callback=log_cb
                )

            elif func == '横向补偿':
                macro_list = [int(x.strip()) for x in vals[2].split(',') if x.strip()]
                comp_count = int(vals[1])
                success = process_horizontal_comp(
                    vals[0], vals[1], comp_count, macro_list,
                    float(vals[3]) if vals[3] else None,
                    float(vals[4]) if vals[4] else None,
                    float(vals[5]) if vals[5] else None,
                    float(vals[6]) if vals[6] else None,
                    log_callback=log_cb
                )

            elif func == '坐标补齐':
                success = process_fill_coord(vals[0], vals[1], log_callback=log_cb)

            elif func == '按段拆分':
                out_dir = vals[1] if len(vals) > 1 and vals[1] else os.path.dirname(vals[0])
                success = process_split(vals[0], out_dir, log_callback=log_cb)

            elif func == '按段合并':
                out_dir = vals[1] if len(vals) > 1 and vals[1] else vals[0]
                success = process_merge(vals[0], out_dir, log_callback=log_cb)

            else:
                self.log("未知功能")
                return

            if success:
                self.log("✅ 处理完成")
            else:
                self.log("❌ 处理失败，请查看上方日志")

        except Exception as e:
            self.log(f"❌ 异常: {str(e)}")
            import traceback
            self.log(traceback.format_exc())


class NTToolApp(App):
    def build(self):
        return NTToolLayout()


if __name__ == '__main__':
    NTToolApp().run()