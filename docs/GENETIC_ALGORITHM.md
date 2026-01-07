# 遗传算法优化指南

## 概述

本系统集成了遗传算法（Genetic Algorithm, GA）用于优化搜索参数，提升记忆检索的质量和相关性。

## 什么是遗传算法？

遗传算法是一种受生物进化启发的优化算法：

1. **种群（Population）**：多个候选解（参数组合）
2. **适应度（Fitness）**：评估每个候选解的质量
3. **选择（Selection）**：选择表现好的候选解
4. **交叉（Crossover）**：组合两个父代产生子代
5. **变异（Mutation）**：随机改变参数引入多样性
6. **进化（Evolution）**：重复上述过程多代

## 可优化的搜索参数

```python
class SearchParameters:
    rrf_k: float = 60.0              # RRF 融合 k 参数 (范围: 1-200)
    decay_lambda: float = 0.01       # 记忆衰减率 (范围: 0.001-0.1)
    importance_floor: float = 0.2    # 重要性下限 (范围: 0.0-0.5)
    type_mismatch_penalty: float = 0.35  # 类型不匹配惩罚 (范围: 0.1-0.9)
    bm25_weight: float = 0.5         # BM25 权重 (范围: 0.0-1.0)
    vector_weight: float = 0.5       # 向量权重 (范围: 0.0-1.0)
```

### 参数说明

#### 1. rrf_k (RRF Fusion K)
- **作用**：控制 RRF 融合算法中的排名平滑程度
- **默认值**：60.0
- **影响**：较小的 k 值会让高排名结果的优势更明显
- **公式**：`score = 1 / (k + rank)`

#### 2. decay_lambda (Memory Decay Rate)
- **作用**：控制记忆随时间衰减的速度
- **默认值**：0.01
- **影响**：较大的值会让旧记忆更快失去重要性
- **公式**：`importance *= exp(-lambda * days)`

#### 3. importance_floor (Importance Floor)
- **作用**：确保低重要性记忆仍有最小权重
- **默认值**：0.2
- **影响**：防止低重要性记忆被完全忽略

#### 4. type_mismatch_penalty (Type Mismatch Penalty)
- **作用**：当记忆类型不匹配偏好时的惩罚系数
- **默认值**：0.35
- **影响**：较小值对类型不匹配更宽容

#### 5. bm25_weight & vector_weight (Search Weights)
- **作用**：平衡关键词搜索和语义搜索的贡献
- **默认值**：各 0.5
- **影响**：调整两种搜索方式的相对重要性

## 使用方法

### 1. 命令行示例

```bash
# 运行优化演示
python examples/genetic_optimization_demo.py
```

### 2. API 调用

```bash
# 优化搜索参数
curl -X POST http://localhost:8000/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "test_queries": [
      {"player_id": "p1", "npc_id": "n1", "query": "找回丢失的剑"},
      {"player_id": "p1", "npc_id": "n1", "query": "昨天的对话"}
    ],
    "ground_truth": [
      ["mem1", "mem2", "mem3"],
      ["mem4", "mem5"]
    ],
    "ga_config": {
      "population_size": 20,
      "generations": 10,
      "mutation_rate": 0.1
    }
  }'
```

### 3. Python 代码

```python
from src.memory.genetic_optimizer import (
    GeneticOptimizer,
    GAConfig,
    SearchParameters,
    create_fitness_function,
)

# 配置遗传算法
config = GAConfig(
    population_size=20,      # 种群大小
    generations=10,          # 进化代数
    mutation_rate=0.1,       # 变异概率
    mutation_strength=0.2,   # 变异强度
    crossover_rate=0.7,      # 交叉概率
    elitism_count=2,         # 精英保留数
    tournament_size=3,       # 锦标赛选择大小
)

# 创建优化器
optimizer = GeneticOptimizer(config)

# 定义适应度函数（评估参数质量）
def fitness_func(params: SearchParameters) -> float:
    # 在测试数据上评估搜索质量
    # 返回 0-1 之间的分数，越高越好
    score = evaluate_search_quality(params)
    return score

# 运行优化
result = optimizer.optimize(fitness_func=fitness_func)

# 查看结果
print(f"最佳适应度: {result.best_fitness}")
print(f"最佳参数:")
for key, value in result.best_parameters.to_dict().items():
    print(f"  {key}: {value:.4f}")
```

## GA 配置参数

| 参数 | 默认值 | 范围 | 说明 |
|------|--------|------|------|
| `population_size` | 20 | 5-100 | 种群大小，越大搜索空间越广但越慢 |
| `generations` | 10 | 1-100 | 进化代数，越多越可能找到最优解 |
| `mutation_rate` | 0.1 | 0.0-1.0 | 每个参数变异的概率 |
| `mutation_strength` | 0.2 | 0.0-1.0 | 变异的相对强度 (±20%) |
| `crossover_rate` | 0.7 | 0.0-1.0 | 发生交叉的概率 |
| `elitism_count` | 2 | 0-10 | 直接保留到下一代的精英个体数 |
| `tournament_size` | 3 | 2-10 | 锦标赛选择时的竞争者数量 |

## 适应度函数

适应度函数评估参数的质量。常用指标：

### 1. Precision@K
```python
def precision_at_k(results: List[str], expected: List[str], k: int) -> float:
    """计算前 K 个结果中相关结果的比例"""
    if not results or not expected:
        return 0.0
    relevant = set(expected)
    found = len(set(results[:k]) & relevant)
    return found / min(k, len(results))
```

### 2. Mean Average Precision (MAP)
```python
def mean_average_precision(all_results: List[List[str]], 
                          all_expected: List[List[str]]) -> float:
    """计算多个查询的平均精度"""
    if not all_results:
        return 0.0
    scores = []
    for results, expected in zip(all_results, all_expected):
        scores.append(average_precision(results, expected))
    return sum(scores) / len(scores)
```

### 3. NDCG (Normalized Discounted Cumulative Gain)
```python
def ndcg_at_k(results: List[str], relevance: Dict[str, float], k: int) -> float:
    """计算 NDCG@K 分数"""
    dcg = sum(relevance.get(r, 0.0) / math.log2(i + 2) 
              for i, r in enumerate(results[:k]))
    ideal_dcg = sum(sorted(relevance.values(), reverse=True)[:k][i] / math.log2(i + 2)
                   for i in range(min(k, len(relevance))))
    return dcg / ideal_dcg if ideal_dcg > 0 else 0.0
```

## 优化流程

### Step 1: 收集测试数据

```python
# 准备测试查询
test_queries = [
    {"player_id": "p1", "npc_id": "npc_merchant", "query": "购买药水"},
    {"player_id": "p1", "npc_id": "npc_merchant", "query": "上次交易"},
    {"player_id": "p2", "npc_id": "npc_guard", "query": "城门任务"},
]

# 准备期望结果（Ground Truth）
ground_truth = [
    ["mem_trade_001", "mem_trade_002"],
    ["mem_dialogue_015", "mem_trade_001"],
    ["mem_quest_042", "mem_dialogue_033"],
]
```

### Step 2: 定义评估函数

```python
def evaluate_params(params: SearchParameters) -> float:
    """评估参数在测试集上的表现"""
    total_score = 0.0
    for query, expected in zip(test_queries, ground_truth):
        # 使用这些参数执行搜索
        results = search_with_params(query, params)
        # 计算精度
        score = precision_at_k(results, expected, k=5)
        total_score += score
    return total_score / len(test_queries)
```

### Step 3: 运行优化

```python
optimizer = GeneticOptimizer(GAConfig(
    population_size=30,
    generations=20,
))

result = optimizer.optimize(fitness_func=evaluate_params)
```

### Step 4: 应用最佳参数

```python
# 保存最佳参数
best_params = result.best_parameters
with open('optimized_params.json', 'w') as f:
    json.dump(best_params.to_dict(), f)

# 在生产中使用
# TODO: 将参数应用到搜索系统配置
```

## 性能考虑

### 计算成本

- **时间复杂度**：O(population_size × generations × test_queries)
- **建议**：
  - 开发环境：`population_size=10, generations=5`
  - 测试环境：`population_size=20, generations=10`
  - 生产优化：`population_size=50, generations=30`

### 并行化

遗传算法天然支持并行化：

```python
from concurrent.futures import ThreadPoolExecutor

def parallel_evaluate(population, fitness_func):
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fitness_func, ind.parameters) 
                  for ind in population]
        results = [f.result() for f in futures]
    return results
```

## 高级技巧

### 1. 自适应变异率

```python
def adaptive_mutation_rate(generation, max_generations):
    """随着进化降低变异率，精细调优"""
    return 0.3 * (1 - generation / max_generations) + 0.05
```

### 2. 多目标优化

```python
def multi_objective_fitness(params: SearchParameters) -> float:
    """同时优化精度和速度"""
    precision = evaluate_precision(params)
    speed = evaluate_speed(params)
    return 0.7 * precision + 0.3 * speed
```

### 3. 迁移学习

```python
# 使用之前的优化结果作为初始种群
previous_best = load_previous_best_params()
initial_population = [previous_best] + generate_random_population(19)

result = optimizer.optimize(
    fitness_func=fitness_func,
    initial_population=initial_population
)
```

## 监控与调试

### 查看进化历史

```python
import matplotlib.pyplot as plt

# 绘制适应度曲线
generations = range(len(result.fitness_history))
best_fitness = [f[0] for f in result.fitness_history]
avg_fitness = [f[1] for f in result.fitness_history]

plt.plot(generations, best_fitness, label='Best')
plt.plot(generations, avg_fitness, label='Average')
plt.xlabel('Generation')
plt.ylabel('Fitness')
plt.legend()
plt.show()
```

### 参数收敛分析

```python
# 检查参数是否收敛
for gen_pop in result.population_history:
    rrf_values = [ind.parameters.rrf_k for ind in gen_pop]
    print(f"Gen {gen}: RRF_k std={np.std(rrf_values):.2f}")
```

## 常见问题

### Q1: 如何选择种群大小和代数？

**A**: 平衡搜索质量和计算时间：
- 小问题（<10参数）：`population_size=15, generations=10`
- 中等问题：`population_size=30, generations=20`
- 大问题：`population_size=50, generations=50`

### Q2: 优化结果不稳定怎么办？

**A**: 尝试：
1. 增加种群大小
2. 增加精英保留数 (elitism_count)
3. 降低变异率和强度
4. 运行多次取最佳结果

### Q3: 如何避免过拟合测试集？

**A**: 
1. 使用交叉验证
2. 保留验证集
3. 定期在真实查询上测试
4. 监控生产环境指标

## 最佳实践

1. **逐步优化**：先优化核心参数（rrf_k, decay_lambda），再优化权重
2. **版本控制**：记录每次优化的参数和性能
3. **A/B 测试**：在生产环境中比较新旧参数
4. **持续监控**：跟踪搜索质量指标，定期重新优化
5. **文档记录**：记录优化过程和决策

## 参考资料

- [遗传算法入门](https://en.wikipedia.org/wiki/Genetic_algorithm)
- [RRF 融合算法论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [信息检索评估指标](https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval))

## 下一步

1. 收集真实搜索查询和用户反馈
2. 建立评估基准（Baseline）
3. 运行首次优化
4. 部署并监控改进效果
5. 定期重新优化以适应数据变化
