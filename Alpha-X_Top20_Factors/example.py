import json
import pandas as pd
import numpy as np
import os

def load_and_run_factors():
    # 1. 加载因子包
    if not os.path.exists('factors.json'):
        print("错误: 找不到 factors.json 文件")
        return

    with open('factors.json', 'r') as f:
        factors = json.load(f)
    
    print(f"成功加载 {len(factors)} 个因子。")

    # 2. 创建模拟数据 (实际使用请替换为 pd.read_csv)
    print("生成模拟数据...")
    dates = pd.date_range(start='2024-01-01', periods=1000, freq='H')
    df = pd.DataFrame({
        'Open': np.random.uniform(100, 200, 1000),
        'High': np.random.uniform(100, 200, 1000),
        'Low': np.random.uniform(100, 200, 1000),
        'Close': np.random.uniform(100, 200, 1000),
        'Volume': np.random.uniform(1000, 5000, 1000)
    }, index=dates)
    
    # 确保 High/Low 逻辑正确
    df['High'] = df[['Open', 'Close', 'High']].max(axis=1)
    df['Low'] = df[['Open', 'Close', 'Low']].min(axis=1)
    
    # 兼容小写列名 (很多因子习惯用小写)
    df['open'] = df['Open']
    df['high'] = df['High']
    df['low'] = df['Low']
    df['close'] = df['Close']
    df['volume'] = df['Volume']

    # 3. 批量计算
    results = pd.DataFrame(index=df.index)
    
    print("-" * 50)
    for i, factor in enumerate(factors, 1):
        name = factor['factor_name']
        code = factor['code']
        direction = factor['direction']
        
        print(f"[{i}/{len(factors)}] 计算因子: {name} (方向: {direction})")
        
        try:
            # 动态执行代码，将 calculate_factor 函数加载到局部命名空间
            local_scope = {}
            exec(code, {'pd': pd, 'np': np}, local_scope)
            
            if 'calculate_factor' not in local_scope:
                print(f"  ⚠️ 警告: 因子 {name} 代码中未找到 calculate_factor 函数")
                continue
                
            calc_func = local_scope['calculate_factor']
            
            # 计算原始信号
            raw_signal = calc_func(df.copy())
            
            # 调整方向
            final_signal = raw_signal * direction
            
            # 标准化 (Expanding Window Z-Score)
            # 这是一个稳健的标准化方法，防止未来函数
            mean = final_signal.expanding(min_periods=20).mean()
            std = final_signal.expanding(min_periods=20).std()
            z_score = (final_signal - mean) / (std + 1e-6)
            
            # 存入结果
            results[name] = z_score.fillna(0)
            
        except Exception as e:
            print(f"  ❌ 计算失败: {e}")

    print("-" * 50)
    print("计算完成！前5行结果预览：")
    print(results.head())
    
    # 简单合成一个等权重策略信号
    results['Composite_Signal'] = results.mean(axis=1)
    print("\n合成信号预览：")
    print(results['Composite_Signal'].tail())

if __name__ == "__main__":
    load_and_run_factors()
