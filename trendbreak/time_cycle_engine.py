# time_cycle_engine.py
import numpy as np
import pandas as pd

class TimeCycleEngine:
    # 核心斐波那契数列
    FIBONACCI_SERIES = [21, 34, 55, 89, 144, 233]

    @staticmethod
    def detect_time_resonance(n_total: int, p0_idx: int, p_sub_idx: int = None, tolerance: int = 2) -> dict:
        """
        计算当前K线是否处于时间周期共振窗口
        :param n_total: K线总长度
        :param p0_idx: 宏观最高点P0的索引
        :param p_sub_idx: 中途次顶P_sub的索引（若有）
        :param tolerance: 时间容差窗口（默认±2根K线，以兼容节假日与微幅时滞）
        """
        curr_idx = n_total - 1
        span_from_p0 = curr_idx - p0_idx  # 距离宏观顶部的K线跨度

        matched_targets = []
        is_hit = False

        # 1. 基础斐波那契数列匹配
        for fib in TimeCycleEngine.FIBONACCI_SERIES:
            if abs(span_from_p0 - fib) <= tolerance:
                is_hit = True
                matched_targets.append(f"Fib-{fib}K")

        # 2. 安杰思式等步长倍数对称周期匹配 (如 55 -> 110 -> 165)
        # 若存在中途反弹顶 P_sub，提取其前半段的步长基准
        if p_sub_idx and p_sub_idx > p0_idx:
            step = p_sub_idx - p0_idx
            # 若步长在合理区间（例如 30~65 根K线）
            if 30 <= step <= 65:
                for multiplier in [2, 3, 4]:
                    expected_cycle = step * multiplier
                    if abs(span_from_p0 - expected_cycle) <= tolerance:
                        is_hit = True
                        matched_targets.append(f"Sym-{step}x{multiplier}({expected_cycle}K)")

        # 针对 55 周期的特殊倍数硬核兜底（55x2=110, 55x3=165）
        for mult in [2, 3]:
            target_55 = 55 * mult
            if abs(span_from_p0 - target_55) <= tolerance:
                is_hit = True
                desc = f"Fib-55x{mult}({target_55}K)"
                if desc not in matched_targets:
                    matched_targets.append(desc)

        desc_str = "、".join(matched_targets) if matched_targets else "无"

        return {
            'is_time_resonance': is_hit,
            'span_from_p0': span_from_p0,
            'resonance_desc': desc_str
        }