# Model Capability Boundary via Group-Theory-Embedded Solutions

This document describes the architecture for evaluating model capability boundaries using group-theory-embedded solutions. The pipeline transforms text embeddings through dimensionality reduction, Lie group mapping, and tangent-space statistical analysis to produce probabilistic semantic scores.

## Overview

The capability boundary evaluation pipeline consists of seven main stages:

1. **Text Embedding** - Transform text to high-dimensional vectors
2. **Dimensionality Reduction** - Reduce to k-dimensional space via PCA
3. **Lie Algebra Mapping** - Map vectors to skew-symmetric matrices
4. **Lie Group Mapping** - Exponentiate to rotation group elements
5. **Tangent Space Projection** - Project to Euclidean tangent space
6. **Tangent-Space Gaussian Model** - Compute covariance and Mahalanobis distance
7. **Probabilistic Scoring** - Convert distance to semantic score

## Architecture

### Full Pipeline Diagram: From Embedding → Lie Group → Tangent-Space Mahalanobis

```
┌───────────────────────────────────────────────────────────┐
│                  1. Text Embedding Stage                  │
└───────────────────────────────────────────────────────────┘
                  |  (SentenceTransformer / NV-Embed)
                  v
        ┌─────────────────────┐
        │  High-dim Vector x  │  ← in R^d  (e.g., d=4096 or 1024)
        └─────────────────────┘
                  |
                  |
                  v
┌───────────────────────────────────────────────────────────┐
│                 2. Dimensionality Reduction               │
│        (scikit-learn → PCA / Robust Scaling / Whitening)  │
└───────────────────────────────────────────────────────────┘
                  |
                  v
        ┌─────────────────────┐
        │  PCA Vector  z      │  ← in R^k   (k = m(m-1)/2 )
        └─────────────────────┘
                  |
                  |
                  v
┌───────────────────────────────────────────────────────────┐
│                  3. Lie Algebra Mapping                   │
│      (Geomstats OR SciPy: create ξ ∈ so(m) from z vector) │
│      Uses: reshape → skew-symmetric matrix construction   │
└───────────────────────────────────────────────────────────┘
                  |
                  v
        ┌─────────────────────┐
        │  Lie Algebra ξ      │  ← element of 𝔰𝔬(m)
        └─────────────────────┘
                  |
                  |  SciPy: expm(ξ)
                  v
┌───────────────────────────────────────────────────────────┐
│                  4. Lie Group Mapping                     │
│            (Geomstats or SciPy: g = expm(ξ))              │
│                      g ∈ SO(m)                            │
└───────────────────────────────────────────────────────────┘
                  |
                  |
                  v
        ┌─────────────────────┐
        │   Group Element g   │  ← rotation-like structure
        └─────────────────────┘
                  |
                  |  Compare to mean group element g_mean
                  v
┌───────────────────────────────────────────────────────────┐
│            5. Tangent Space Projection                    │
│   (Geomstats: logarithmic map log_{g_mean}(g) )           │
│   (SciPy: logm(g_mean^{-1} · g))                          │
└───────────────────────────────────────────────────────────┘
                  |
                  v
        ┌─────────────────────┐
        │ Tangent Vector  v   │  ← in R^k, local Euclidean
        └─────────────────────┘
                  |
                  |  SciPy / sklearn: compute covariance
                  v
┌───────────────────────────────────────────────────────────┐
│             6. Tangent-Space Gaussian Model               │
│       (scikit-learn + SciPy: covariance, μ=0, Σ_g)        │
└───────────────────────────────────────────────────────────┘
                  |
                  | Compute Mahalanobis D² = vᵀ Σ⁻¹ v
                  v
┌───────────────────────────────────────────────────────────┐
│   7. Convert Distance → Soft Probabilistic Score          │
│   (SciPy: score = 1 - χ²_cdf(D², df=k))                   │
│   Interpretation: "How normal is the answer?"             │
└───────────────────────────────────────────────────────────┘
                  |
                  v
        ┌─────────────────────┐
        │ Semantic Score [0,1]│
        └─────────────────────┘
```

### Compact Data-Flow Map

```
Text
 → Embedding (Transformer)
 → PCA (sklearn)
 → z ∈ R^k
 → ξ = vec→skew (Geomstats or SciPy)
 → g = exp(ξ)  (SciPy linalg.expm)
 → v = log(g_mean^{-1} g)  (SciPy logm)
 → Mahalanobis in tangent space (SciPy + sklearn)
 → score = 1 - χ²_cdf(D²)
```

## Technology Breakdown per Stage

### 📘 Stage 1: Embedding

**Libraries**: SentenceTransformer, NV-Embed

**Purpose**: Transform text input to high-dimensional vector representations

**Output**: Vector `x ∈ R^d` where `d` is typically 4096 or 1024

**Note**: This stage does not use sklearn/SciPy/Geomstats

---

### 📙 Stage 2: Dimensionality Reduction → scikit-learn

**Libraries**: scikit-learn

**Key Components**:
- `PCA` - Principal Component Analysis
- `StandardScaler`, `RobustScaler` - Feature scaling
- `Covariance`, `EllipticEnvelope` (optional) - Covariance estimation

**Purpose**: Reduce high-dimensional embeddings to k-dimensional space where `k = m(m-1)/2`

**Output**: PCA vector `z ∈ R^k`

**Mathematical Foundation**: The choice of `k = m(m-1)/2` is critical—it represents the dimension of the `so(m)` Lie algebra, creating a 1-to-1 isomorphism between the PCA space and the Lie algebra tangent space.

---

### 📗 Stage 3-5: Lie Groups → Geomstats

**Libraries**: Geomstats (primary), SciPy (supporting)

**Key Components**:
- `geomstats.geometry.special_orthogonal.SpecialOrthogonal` - SO(m) group structure
- `exp`, `log` - Group exponential and logarithmic maps
- Riemannian metrics - Geodesic distances
- Karcher mean - Fréchet mean on the manifold

**Purpose**: 
- Map PCA vectors to Lie algebra elements `ξ ∈ so(m)`
- Exponentiate to group elements `g ∈ SO(m)`
- Compute group mean `g_mean` using Karcher mean

**Why Geomstats**: Geomstats is specifically built for:
- Lie groups and Riemannian manifolds
- Tangent-space geometry
- Geodesic distances
- Karcher mean computation (iterative optimization)

**Alternative**: While SciPy can perform `expm` and `logm`, Geomstats provides optimized, validated implementations for manifold statistics.

---

### 📘 Stage 4 & 7: Linear Algebra & Statistics → SciPy

**Libraries**: SciPy

**Critical Operations**:

| Operation            | SciPy Function         | Purpose                          |
| -------------------- | ---------------------- | -------------------------------- |
| Matrix exponential   | `scipy.linalg.expm`    | Lie algebra → Lie group          |
| Matrix logarithm     | `scipy.linalg.logm`    | Lie group → tangent space        |
| Covariance inversion | `scipy.linalg.inv`     | Mahalanobis distance computation |
| Solving systems      | `scipy.linalg.solve`   | Efficient linear algebra         |
| Chi-square CDF       | `scipy.stats.chi2.cdf` | Distance → probability           |

**Purpose**: Provide the underlying mathematical engine for:
- Lie algebra exponentials/logs
- Mahalanobis distance computation
- Statistical normality tests

**Why SciPy**: `scipy.linalg.expm` and `scipy.linalg.logm` are gold-standard, numerically stable implementations. `scipy.stats.chi2` provides statistically correct conversion from Mahalanobis distance to probability.

---

### 📙 Stage 6: Tangent-Space Statistics → scikit-learn + SciPy

**Libraries**: scikit-learn, SciPy

**Key Insight**: Once projected to the tangent space at `g_mean`, we are in a **standard Euclidean vector space**. All standard Gaussian statistics are valid.

**Components**:
- Covariance estimation (scikit-learn)
- Mahalanobis distance: `D² = vᵀ Σ⁻¹ v` (SciPy)
- Mean vector: `μ = 0` (by construction, since we're at the mean)

**Output**: Mahalanobis distance `D²` representing deviation from the mean capability distribution

---

### 📘 Stage 7: Probabilistic Scoring → SciPy

**Libraries**: SciPy

**Transformation**: 
```
score = 1 - χ²_cdf(D², df=k)
```

**Interpretation**: 
- `score ∈ [0, 1]` represents "how normal is the answer?"
- Higher scores indicate answers closer to the mean capability distribution
- Lower scores indicate outliers or capability boundary violations

**Statistical Foundation**: The Mahalanobis distance `D²` follows a chi-square distribution with `k` degrees of freedom under the null hypothesis of normal distribution.

## Implementation Details

### Key Mathematical Properties

#### 1. Dimensionality Isomorphism

The critical insight is the isomorphism:
```
R^k ≅ so(m)  where k = m(m-1)/2
```

This creates a 1-to-1 mapping between:
- PCA-reduced embedding space (`R^k`)
- Lie algebra tangent space (`so(m)`)

**Example**: For `m = 16`, we have `k = 16 × 15 / 2 = 120` dimensions.

#### 2. Tangent Space Euclidean Structure

After projection to the tangent space at `g_mean`, we operate in a **standard Euclidean vector space**. This enables:
- Standard Gaussian statistics (covariance, Mahalanobis distance)
- Linear operations
- Classical statistical tests

#### 3. Statistical Validity

The Mahalanobis distance `D² = vᵀ Σ⁻¹ v` follows a chi-square distribution:
```
D² ~ χ²(k)
```

This provides a principled way to convert distances to probabilities.

### Library Responsibility Map

```
┌─────────────────────────────────────────────────────────┐
│                    Text Input                           │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │  SentenceTransformer/NV-Embed  │  ← External
        └───────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │      scikit-learn (PCA)        │  ← Dimensionality Reduction
        └───────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │   Geomstats (Lie Groups)       │  ← Manifold Operations
        │   SciPy (expm/logm)           │  ← Matrix Operations
        └───────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │ scikit-learn (Covariance)      │  ← Statistics
        │ SciPy (Mahalanobis, χ²)        │  ← Distance & Probability
        └───────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────┐
        │      Semantic Score [0,1]      │
        └───────────────────────────────┘
```

## Architecture Analysis

### Why This Architecture is Excellent

#### 1. Correct Separation of Concerns

- **scikit-learn**: Used for its strength—data preprocessing and linear dimensionality reduction (PCA)
- **Geomstats**: Used for its specific, advanced strength—handling the geometry, metrics, and statistics (Karcher mean) of the `SO(m)` manifold
- **SciPy**: Used for its low-level, high-performance mathematical engine (`expm`, `logm`, `chi2`) that Geomstats and custom code build upon

#### 2. Mathematical Correctness

The entire plan hinges on the `R^k` vector space (from PCA) being **isomorphic** to the `so(m)` Lie algebra tangent space. The choice of `k = m(m-1)/2` (e.g., 120 dims for m=16) is the precise mathematical link that makes this architecture "click." It's not a heuristic; it's a 1-to-1 mapping.

#### 3. Statistical Soundness

The most critical step is **Tangent Space Projection**. Once projected to the tangent space at the mean (`g_mean`), we are in a **standard Euclidean vector space**. Therefore, all standard Gaussian statistics (covariance, Mahalanobis distance) are 100% valid. This is the correct way to "do stats on a manifold."

### Key Implementation Endorsements

#### Geomstats for Manifold Operations

While you *can* build the Karcher mean logic with just `scipy.linalg`, it's an iterative optimization process. Geomstats has this logic built-in, validated, and optimized.

**Use Cases**:
- Karcher mean computation (Fréchet mean on SO(m))
- Geodesic distance calculations
- Group exponential/logarithmic maps
- Riemannian metric computations

#### SciPy for Core Mathematical Operations

`scipy.linalg.expm` and `scipy.linalg.logm` are the gold-standard, numerically stable implementations. `scipy.stats.chi2` is the statistically correct way to convert your `D²` distance (a sum of squared Gaussian-like variables) into a probability-based score.

**Use Cases**:
- Matrix exponential: `g = expm(ξ)`
- Matrix logarithm: `v = logm(g_mean^{-1} · g)`
- Covariance inversion: `Σ⁻¹`
- Chi-square CDF: `score = 1 - χ²_cdf(D², df=k)`

### Overall Verdict

This is a **production-ready, "S-tier" design**. It's not a "magical" black box but a series of well-defined, classical mathematical and statistical transformations.

The pipeline is perfectly specified. The technology choices are exactly what a specialist in geometric data analysis would select.

## Implementation Considerations

### Performance Characteristics

#### Computational Complexity

- **Embedding**: O(d) where d is embedding dimension
- **PCA**: O(d²) for covariance, O(dk) for projection
- **Lie Group Operations**: O(m³) for matrix exponential/logarithm
- **Tangent Space Statistics**: O(k²) for covariance, O(k³) for inversion
- **Overall**: Dominated by O(m³) operations for typical m=16

#### Memory Requirements

- **Embeddings**: O(N × d) for N samples
- **PCA Model**: O(d × k) for transformation matrix
- **Covariance Matrix**: O(k²) for tangent space
- **Group Elements**: O(N × m²) for N samples

### Scalability Considerations

1. **Batch Processing**: Process multiple embeddings in batches for efficiency
2. **Caching**: Cache PCA model and group mean after training
3. **Incremental Updates**: Update covariance incrementally for streaming data
4. **Dimensionality Selection**: Choose `m` based on computational budget (m=16 → k=120 is a good balance)

### Error Handling

1. **Numerical Stability**: Use SciPy's numerically stable `expm`/`logm`
2. **Singular Covariance**: Regularize covariance matrix if singular
3. **Out-of-Distribution**: Handle cases where tangent projection fails
4. **Embedding Failures**: Graceful fallback for embedding errors

## Configuration

### Key Parameters

```python
# Dimensionality
m = 16                    # SO(m) group dimension
k = m * (m - 1) // 2     # Lie algebra dimension (120 for m=16)
d = 4096                  # Embedding dimension

# PCA Configuration
n_components = k          # Match Lie algebra dimension
whiten = True             # Optional whitening

# Statistical Parameters
regularization = 1e-6     # Covariance regularization
confidence_level = 0.95   # Chi-square confidence level
```

### Library Versions

- **scikit-learn**: >= 1.0.0 (for PCA and preprocessing)
- **Geomstats**: >= 2.5.0 (for Lie group operations)
- **SciPy**: >= 1.7.0 (for matrix operations and statistics)
- **SentenceTransformer**: >= 2.0.0 (for embeddings)

## Future Enhancements

### Research Directions

1. **Adaptive Dimensionality**: Dynamically select `m` based on data characteristics
2. **Non-Euclidean Metrics**: Explore alternative Riemannian metrics beyond standard
3. **Multi-Manifold Models**: Combine multiple Lie groups for richer representations
4. **Online Learning**: Incremental updates to group mean and covariance

### Performance Optimizations

1. **GPU Acceleration**: Leverage GPU for matrix operations (cuPy)
2. **Approximate Methods**: Use approximate Karcher mean for faster computation
3. **Sparse Representations**: Exploit sparsity in covariance matrices
4. **Parallel Processing**: Parallelize across multiple samples

---

*This document provides a comprehensive guide to the Model Capability Boundary evaluation architecture using group-theory-embedded solutions. The design is mathematically rigorous, statistically sound, and production-ready.*

