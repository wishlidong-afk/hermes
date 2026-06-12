from __future__ import annotations

from typing import Dict


_GENERIC_BY_MODULE = {
    "A": {
        "professional_explain": "宏观流动性、情绪、广度和大盘派发信号的综合压力。",
        "plain_explain": "看大环境是不是开始缺钱、过热或集体转弱。",
        "data_hint": "主要来自 QQQ/SPY/VIX、情绪、资金面和软数据代理。",
    },
    "B": {
        "professional_explain": "标的自身过热、估值、期权波动和高位损伤风险。",
        "plain_explain": "看这个票是不是涨太快、太贵、太拥挤。",
        "data_hint": "主要来自 RSI、MA200 乖离、60日高点回撤、VVIX/SKEW 和估值分位。",
    },
    "C": {
        "professional_explain": "技术结构、趋势破位、急跌、派发日、ATR 吊灯和再建仓线风险。",
        "plain_explain": "看盘面结构有没有坏，关键支撑有没有被砸穿。",
        "data_hint": "主要来自均线结构、收益率、AVWAP、派发天数、ATR 和 MA220。",
    },
    "D": {
        "professional_explain": "标的专属风险层，包括雷达确认、成分资金流和行业/资产特有压力。",
        "plain_explain": "看这个标的自己的发动机和内部零件有没有出问题。",
        "data_hint": "MSTR 参考自身/BTC；FNGU 参考 QQQ/成分；SOXL 参考 SOXX/半导体成分。",
    },
}


FACTOR_EXPLAINS: Dict[str, Dict[str, str]] = {
    "A1_QQQ_MA200_BREAK": {
        "professional_explain": "QQQ 跌破 MA200 代表纳指长期趋势进入防守区，是宏观核爆路由的核心因子之一。",
        "plain_explain": "纳指大底盘跌破长期生命线，杠杆仓位要明显收缩。",
        "data_hint": "QQQ daily close 与 QQQ MA200。",
    },
    "A1_VIX_COMPLACENCY": {
        "professional_explain": "VIX 极低代表波动率压缩后的拥挤风险；VIX 高企叠加趋势破位代表恐慌风险。",
        "plain_explain": "太安静或突然太恐慌都危险。",
        "data_hint": "VIX close，必要时结合 QQQ EMA20/EMA50。",
    },
    "A2_CNN_FEAR_GREED": {
        "professional_explain": "CNN Fear & Greed 缺失占位；用于衡量散户与市场情绪极端。",
        "plain_explain": "市场情绪表没接上时不能当成安全。",
        "data_hint": "CNN Fear & Greed 或等价情绪代理。",
    },
    "A2_AAII_BULL": {
        "professional_explain": "AAII 牛熊差和牛市分位衡量散户调查的乐观拥挤度。",
        "plain_explain": "散户过度看多时，顶部风险升高。",
        "data_hint": "AAII bull-bear spread 与 bull percentile。",
    },
    "A2_NAAIM": {
        "professional_explain": "NAAIM 曝险指数衡量主动管理人权益仓位拥挤程度。",
        "plain_explain": "机构仓位太满，后续买盘可能不足。",
        "data_hint": "NAAIM exposure 与历史分位。",
    },
    "A2_CBOE_EQUITY_PCR": {
        "professional_explain": "权益 Put/Call Ratio 低位代表看涨拥挤，高位代表恐慌对冲。",
        "plain_explain": "期权市场一边倒时要警惕反转。",
        "data_hint": "CBOE equity PCR 与历史分位。",
    },
    "A3_COMPONENT_BREADTH": {
        "professional_explain": "成分广度过热或短期塌陷都表示大盘结构进入脆弱状态。",
        "plain_explain": "要么大家涨得太齐，要么突然很多票掉队，都不舒服。",
        "data_hint": "成分股站上 50/200 日均线比例和 5 日变化。",
    },
    "A4_QQQ_STRETCH": {
        "professional_explain": "QQQ 距 EMA20 过远或 RSI 过高表示短线风险收益不对称。",
        "plain_explain": "纳指短线拉太猛，容易回踩。",
        "data_hint": "QQQ close、EMA20、RSI14。",
    },
    "A5_NET_LIQUIDITY": {
        "professional_explain": "净流动性收缩会降低高 beta/杠杆资产的估值承载力，是宏观核爆核心因子。",
        "plain_explain": "市场水位下降，杠杆资产最容易先挨打。",
        "data_hint": "净流动性 10 日变化分位或等价代理。",
    },
    "A6_FUND_FLOW": {
        "professional_explain": "QQQ CMF/MFI/AD 斜率衡量大盘资金流入流出和量价健康度。",
        "plain_explain": "纳指有没有被真金白银托住。",
        "data_hint": "QQQ CMF20、MFI14、AD slope20。",
    },
    "A7_VIX_TERM_STRUCTURE": {
        "professional_explain": "VIX 高于 VIX3M 或期限结构倒挂代表短端恐慌升温，是宏观核爆核心因子。",
        "plain_explain": "市场开始买短期保险，风险已经迫近。",
        "data_hint": "VIX close 与 VIX3M close。",
    },
    "A8_QQQ_DISTRIBUTION": {
        "professional_explain": "QQQ/SPY 派发日聚集代表机构出货压力，是宏观核爆核心因子。",
        "plain_explain": "指数没大跌，但大资金可能在悄悄卖。",
        "data_hint": "QQQ/SPY 25 日派发天数。",
    },
    "B1_RSI_OVERHEAT": {
        "professional_explain": "多周期 RSI 过热衡量动量拥挤和短线均值回归风险。",
        "plain_explain": "涨得太快，容易被洗。",
        "data_hint": "标的 RSI14，以及 MSTR weekly RSI 或 FNGS/SOXX 雷达 RSI。",
    },
    "B2_MA200_EXTENSION": {
        "professional_explain": "价格相对 MA200 乖离越大，后续回撤的非对称风险越高。",
        "plain_explain": "离长期均线太远，拉回来的空间也大。",
        "data_hint": "标的 close 与 MA200。",
    },
    "B3_POST_PEAK_DAMAGE": {
        "professional_explain": "从近 60 日高点回撤衡量顶部后损伤程度。",
        "plain_explain": "已经从高位摔下来多少。",
        "data_hint": "标的 drawdown_60d_high_pct。",
    },
    "B4_CBOE_OPTIONS_STRESS": {
        "professional_explain": "VVIX/SKEW 极端代表期权尾部风险定价升温。",
        "plain_explain": "期权市场开始给大波动买保险。",
        "data_hint": "VVIX 分位、SKEW 指数与分位。",
    },
    "B5_SOCIAL_EUPHORIA": {
        "professional_explain": "社媒狂热缺失占位；用于识别散户叙事泡沫。",
        "plain_explain": "网上太亢奋时不能默认安全。",
        "data_hint": "社媒热度、搜索趋势或可替代情绪代理。",
    },
    "B6_VALUATION_HEAT": {
        "professional_explain": "估值分位衡量基本面/溢价过热，避免只看价格趋势。",
        "plain_explain": "不是涨就可以买，还要看贵不贵。",
        "data_hint": "FNGS/SOXX forward PE 分位，MSTR mNAV 溢价分位。",
    },
    "C10_MACRO_TREND_STRUCTURE": {
        "professional_explain": "EMA50、Minervini 多头排列、Weinstein 150/200 日结构合并为单一超级趋势因子，避免均线共线性重复扣分。",
        "plain_explain": "把一堆类似均线信号合成一个总判断：趋势有没有坏。",
        "data_hint": "close、EMA50、MA50、MA150、MA200。",
    },
    "C6_SHARP_DROP": {
        "professional_explain": "短期急跌捕捉高 beta 资产从顶部快速坍塌的初段。",
        "plain_explain": "两天内砸太狠，先防守。",
        "data_hint": "标的 2 日收益率。",
    },
    "C7_AVWAP_PLATFORM_SUPPORT": {
        "professional_explain": "峰值锚定 AVWAP 与平台低点用于识别主力成本区和短线支撑破坏。",
        "plain_explain": "跌破主力成本线或平台支撑，就别硬扛。",
        "data_hint": "close、20 日锚定 AVWAP、20 日平台低点。",
    },
    "C8_DISTRIBUTION_PRESSURE": {
        "professional_explain": "派发日累积衡量放量下跌和机构减仓压力。",
        "plain_explain": "一段时间里放量跌的天数太多。",
        "data_hint": "25 日派发天数。",
    },
    "C9_CHANDELIER_BREAK": {
        "professional_explain": "22 日 Chandelier Exit 使用 4.5x ATR，给 3 倍杠杆噪音留呼吸空间，只捕捉实质破位。",
        "plain_explain": "不是小震荡就踢出局，只有真跌穿追踪止损才报警。",
        "data_hint": "close 与 22D highest high - 4.5 × ATR14。",
    },
    "C11_MA220_REBUILD_GAP": {
        "professional_explain": "MA220 是再建仓审计线，站上并拉开距离才更适合重新加风险。",
        "plain_explain": "刚回到安全线附近还别太急。",
        "data_hint": "close 与 MA220。",
    },
    "C12_VOL_EXPANSION": {
        "professional_explain": "20 日实现波动率扩张表示杠杆损耗和尾部风险上升。",
        "plain_explain": "波动太大时，3 倍产品会被来回磨。",
        "data_hint": "20 日年化实现波动率。",
    },
    "D1_ASSET_MA200_BREAK": {
        "professional_explain": "标的自身跌破 MA200 是专属长期趋势破位。",
        "plain_explain": "这只标的自己的长期生命线破了。",
        "data_hint": "标的 close 与 MA200。",
    },
    "D2_ASSET_MA220_BREAK": {
        "professional_explain": "标的自身跌破 MA220 表示再建仓结构未通过审计。",
        "plain_explain": "还没重新站稳建仓线。",
        "data_hint": "标的 close 与 MA220。",
    },
    "D3_TRAILING_PEAK_DAMAGE": {
        "professional_explain": "60 日高点回撤叠加 EMA50 破位提前替代滞后的 MA200 收尸信号。",
        "plain_explain": "从高位跌太多且跌破中线，不能等到更晚。",
        "data_hint": "drawdown_60d_high_pct、close、EMA50。",
    },
    "D4_RADAR_CONFIRMATION": {
        "professional_explain": "用 MSTR/BTC、FNGU/QQQ、SOXL/SOXX 雷达确认底层趋势是否同步破位。",
        "plain_explain": "看它背后的主控指数有没有一起坏。",
        "data_hint": "MSTR: BTC；FNGU: QQQ；SOXL: SOXX 的 close/MA200/EMA50。",
    },
    "D_M3_BTC_VOLATILITY_PROXY": {
        "professional_explain": "BTC 波动、回撤和收益压力用于代理 MSTR 的底层资产风险。",
        "plain_explain": "MSTR 背后是 BTC，BTC 抖得厉害时 MSTR 也危险。",
        "data_hint": "BTC realized_vol20、return_10d、drawdown_60d_high_pct。",
    },
    "D_M3_BTC_RISK_COMPOSITE": {
        "professional_explain": "在同一 4 分 D_M3 预算内合并 BTC 价格压力与已核验链上交易所压力，不扩张 D 模块 cap。",
        "plain_explain": "BTC 本身或链上交易所流入压力变危险时，MSTR 的底层风险也升高。",
        "data_hint": "BTC realized_vol20/return_10d/drawdown_60d_high_pct；Coin Metrics exchange inflow/netflow pressure。",
    },
    "D_M4_BALANCE_SHEET_PROXY": {
        "professional_explain": "MSTR 资产负债表/融资风险缺失占位。",
        "plain_explain": "MSTR 的债务和融资风险还需要接数据。",
        "data_hint": "可接公司债、可转债、融资成本或 mNAV 压力代理。",
    },
    "D_M5_CRYPTO_SENTIMENT": {
        "professional_explain": "加密市场情绪风险缺失占位。",
        "plain_explain": "币圈情绪太热或太恐慌时会影响 MSTR。",
        "data_hint": "可接 BTC funding、ETF flow、crypto fear/greed。",
    },
    "D_F4_COMPONENT_FLOW": {
        "professional_explain": "FNGU 核心成分资金流同步转弱代表内部派发。",
        "plain_explain": "FNGU 里面的大票一起流出，就不能只看指数表面。",
        "data_hint": "FNGU 成分 CMF20、MFI14、AD slope20。",
    },
    "D_S4_COMPONENT_FLOW": {
        "professional_explain": "SOXL 半导体成分资金流同步转弱代表板块内部派发。",
        "plain_explain": "半导体龙头们一起流出，SOXL 风险会被放大。",
        "data_hint": "SOXL/SOXX 成分 CMF20、MFI14、AD slope20。",
    },
    "A9_HY_OAS": {
        "professional_explain": "高收益信用利差走阔是 risk-off 最可靠的领先信号，独立于价/量/情绪。",
        "plain_explain": "垃圾债开始要更高补偿，说明聪明钱在撤离风险。",
        "data_hint": "FRED ICE BofA US HY OAS（BAMLH0A0HYM2）分位。",
    },
    "A10_REAL_RATE": {
        "professional_explain": "10Y 实际利率上升直接压缩长久期成长/加密/半导体估值。",
        "plain_explain": "扣掉通胀后的真实利率走高，高估值的票最先挨打。",
        "data_hint": "FRED 10Y TIPS 实际收益率（DFII10）分位。",
    },
    "A11_DOLLAR": {
        "professional_explain": "广义美元走强代表全球美元流动性收紧，压制风险资产，尤其加密。",
        "plain_explain": "美元变贵，全球的钱变紧，高 beta 资产承压。",
        "data_hint": "FRED 广义美元指数（DTWEXBGS）分位。",
    },
    "A12_YIELD_CURVE": {
        "professional_explain": "10Y-3M 收益率曲线倒挂是周期/衰退压力的经典信号。",
        "plain_explain": "短期利率比长期还高，说明市场担心经济要走弱。",
        "data_hint": "FRED 10年-3月期限利差（T10Y3M）。",
    },
    "A13_CREDIT_ETF": {
        "professional_explain": "高收益债 ETF 相对国债（HYG/IEF）走弱是 OAS 的日频免费代理。",
        "plain_explain": "垃圾债跑输国债，风险偏好在退潮。",
        "data_hint": "HYG/IEF 相对强弱比值的历史分位。",
    },
    "A14_CONCENTRATION": {
        "professional_explain": "等权相对市值加权（RSP/SPY）走弱代表少数权重股撑盘，牛尾脆弱。",
        "plain_explain": "只有几个大票在硬撑指数，内部其实在转弱。",
        "data_hint": "RSP/SPY 相对强弱比值的历史分位。",
    },
    "A15_DEFENSIVE_ROTATION": {
        "professional_explain": "防守板块相对周期板块跑赢代表资金转入避险，风险偏好下降。",
        "plain_explain": "钱往公用/必需/医疗这些防守票里躲，说明在避险。",
        "data_hint": "(XLP+XLU+XLV)/(XLY+XLI+XLF) 等权比值分位。",
    },
    "A16_FINANCIAL_STRESS": {
        "professional_explain": "金融板块相对大盘（XLF/SPY）走弱常是信用/系统性压力先兆。",
        "plain_explain": "银行金融股带头跑输，往往是系统性风险的前兆。",
        "data_hint": "XLF/SPY 相对强弱比值分位（可叠加 KRE 区域银行）。",
    },
    "A17_NFCI": {
        "professional_explain": "芝加哥联储金融条件指数（NFCI）是现成的金融松紧综合分；走高=条件收紧=风险上升。",
        "plain_explain": "一个把利率/信用/杠杆都揉成一个数的'金融松紧表'，变紧时高 beta 先承压。",
        "data_hint": "FRED NFCI 历史分位（>0 即比平均更紧）。",
    },
    "A18_MOVE": {
        "professional_explain": "MOVE 指数=债市隐含波动率（债券版 VIX）；常领先股市 VIX 与 risk-off。",
        "plain_explain": "债市先慌，股市后慌——债券波动率飙升往往是前兆。",
        "data_hint": "^MOVE 收盘的历史分位。",
    },
    "A19_NDX_CONCENTRATION": {
        "professional_explain": "等权纳指(QQQE)相对市值权(QQQ)走弱=纳指广度收窄，少数巨头撑指数，是科技顶经典 tell。",
        "plain_explain": "纳指只剩几个大票在硬撑，等权版跑输，说明内部其实在转弱。",
        "data_hint": "QQQE/QQQ 相对强弱比值的历史分位（低=广度差）。",
    },
    "A20_COT_NQ": {
        "professional_explain": "CFTC COT 纳指期货（NQ）机构+杠杆基金综合净多/持仓量。分位高=多头过度拥挤，历史上是拉高出货的先兆。",
        "plain_explain": "期货市场大资金净多头拥挤到极致，通常意味着已经没有新买家，下行风险上升。",
        "data_hint": "CFTC 每周发布（周五，数据为周二快照）；资产管理+杠杆基金净多/持仓量历史分位。",
    },
}


def explain_factor(factor_id: str, module: str | None = None) -> Dict[str, str]:
    explicit = FACTOR_EXPLAINS.get(str(factor_id or ""))
    if explicit:
        return dict(explicit)
    mod = (module or str(factor_id or "")[:1] or "").upper()
    base = dict(_GENERIC_BY_MODULE.get(mod, {
        "professional_explain": "该因子用于补充逃顶评分的风险证据。",
        "plain_explain": "这是一个辅助风险提示。",
        "data_hint": "查看该因子的原始 explain 与缺失字段。",
    }))
    base["professional_explain"] = f"{factor_id}: {base['professional_explain']}"
    return base
