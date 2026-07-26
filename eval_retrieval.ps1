$API = "http://localhost:8000"

function Test-Recall($docs, $keywords, $k) {
    $top = $docs | Select-Object -First $k
    if (-not $top) { return 0 }
    $hits = 0
    foreach ($doc in $top) {
        $text = ($doc.text -join " ").ToLower()
        foreach ($kw in $keywords) {
            if ($text -match [regex]::Escape($kw.ToLower())) {
                $hits++
                break
            }
        }
    }
    $denom = [math]::Min($k, @($top).Count)
    if ($denom -eq 0) { return 0 }
    return [math]::Round($hits / $denom, 2)
}

$QUERIES = @(
    @{q="动态计算图";            kw=@("动态计算图","Define-by-Run","PyTorch")}
    @{q="Cross-Encoder 和 Bi-Encoder 的区别"; kw=@("Cross-Encoder","Bi-Encoder","两阶段","reranker")}
    @{q="Docker 镜像层缓存优化"; kw=@("Docker","层缓存","Dockerfile","镜像体积")}
    @{q="RRF 融合公式";          kw=@("RRF","Reciprocal Rank Fusion","BM25")}
    @{q="如何减少 LLM 幻觉";     kw=@("RAG","检索增强","幻觉","知识库")}
)

$dense_r5_total = 0; $dense_r10_total = 0
$hybrid_r5_total = 0; $hybrid_r10_total = 0
$rerank_r5_total = 0; $rerank_r10_total = 0
$count = 0

$fmt = [string]::Format

Write-Host ("{0}" -f ("=" * 70))
Write-Host ("{0,70}" -f "检索评测报告")
Write-Host ("{0,70}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"))
Write-Host ("知识库: 28篇 | 测试: {0}题" -f $QUERIES.Count)
Write-Host ("{0}" -f ("=" * 70))

foreach ($qi in 0..($QUERIES.Count-1)) {
    $q = $QUERIES[$qi]
    $qNum = $qi + 1
    Write-Host ([string]::Format("[Q{0}] {1}", $qNum, $q.q))
    Write-Host ([string]::Format("      期望: {0}", ($q.kw -join ", ")))
    Write-Host ""

    foreach ($method in @("dense", "hybrid", "reranked")) {
        $useReranker = ($method -eq "reranked")
        if ($useReranker) { $rr = "true" } else { $rr = "false" }
        $label = @{dense="单路向量"; hybrid="混合+RRF"; reranked="混合+Reranker"}[$method]

        try {
            $bodyStr = '{"question":"' + $q.q.Replace('"','\"') + '","top_k":10,"use_reranker":' + $rr + '}'
            $tmpFile = [System.IO.Path]::GetTempFileName()
            [System.IO.File]::WriteAllText($tmpFile, $bodyStr, [System.Text.UTF8Encoding]::new($false))
            $raw = curl.exe -s -X POST "$API/query/hybrid" -H "X-API-Key: rag-secret-key-2024" -H "Content-Type: application/json" -d "@$tmpFile" 2>$null
            Remove-Item $tmpFile -ErrorAction SilentlyContinue

            $resp = $raw | ConvertFrom-Json
            if (-not $resp) { Write-Host "  $label : 空"; continue }
            $result = $resp.result

            if ($method -eq "dense")      { $docs = $result.dense_top }
            elseif ($method -eq "hybrid") { $docs = $result.hybrid_top }
            else                          { $docs = $result.reranked }

            if (-not $docs -or @($docs).Count -eq 0) { Write-Host "  $label : 空"; continue }

            $r5 = Test-Recall $docs $q.kw 5
            $r10 = Test-Recall $docs $q.kw 10
            $n = @($docs).Count

            if ($method -eq "dense")   { $dense_r5_total += $r5; $dense_r10_total += $r10 }
            if ($method -eq "hybrid")  { $hybrid_r5_total += $r5; $hybrid_r10_total += $r10 }
            if ($method -eq "reranked"){ $rerank_r5_total += $r5; $rerank_r10_total += $r10 }

            Write-Host ("  {0,-14} R@5={1} R@10={2} 返回={3}" -f $label, $r5, $r10, $n)
        } catch {
            Write-Host "  $label : 错误 $($_.Exception.Message)"
        }
    }
    $count++
    Write-Host ""
}

Write-Host ("{0}" -f ("=" * 70))
Write-Host "汇总" -ForegroundColor Green
Write-Host ("{0,-16} {1,-10} {2,-10} {3,-10}" -f "方法", "R@5平均", "R@10平均", "综合分")
Write-Host ("{0}" -f ("-" * 50))

$ms = @(
    @{n="单路向量";    r5=[math]::Round($dense_r5_total / $count, 2);  r10=[math]::Round($dense_r10_total / $count, 2)}
    @{n="混合+RRF";   r5=[math]::Round($hybrid_r5_total / $count, 2); r10=[math]::Round($hybrid_r10_total / $count, 2)}
    @{n="混合+Reranker"; r5=[math]::Round($rerank_r5_total / $count, 2); r10=[math]::Round($rerank_r10_total / $count, 2)}
)

foreach ($m in $ms) {
    $s = [math]::Round(($m.r5 + $m.r10) / 2, 2)
    Write-Host ("{0,-16} {1,-10} {2,-10} {3,-10}" -f $m.n, $m.r5, $m.r10, $s)
}
Write-Host ("{0}" -f ("=" * 70))

$best = ($ms | Sort-Object -Property r10 -Descending | Select-Object -First 1).n
Write-Host "结论：$best 在 Recall@10 上表现最优"
