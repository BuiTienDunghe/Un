param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$SampleFile = ""
)

$health = Invoke-RestMethod "$BaseUrl/health"
Write-Host "Health: $($health.status)"
if ($health.status -ne "ok") { throw "API dependencies are not ready." }

$models = Invoke-RestMethod "$BaseUrl/models"
Write-Host "General model: $($models.models.general.name)"

$chat = Invoke-RestMethod -Method Post "$BaseUrl/chat" -ContentType "application/json" -Body '{"message":"Reply with a short readiness confirmation."}'
Write-Host "Chat model: $($chat.model_used)"

if ($SampleFile) {
    $upload = curl.exe -s -X POST "$BaseUrl/documents/upload" -F "file=@$SampleFile"
    $document = $upload | ConvertFrom-Json
    $index = Invoke-RestMethod -Method Post "$BaseUrl/documents/index" -ContentType "application/json" -Body (@{document_id=$document.document_id} | ConvertTo-Json)
    $run = $null
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $run = Invoke-RestMethod "$BaseUrl/documents/ingestions/$($index.ingestion_run_id)"
        if ($run.status -in @("indexed", "failed", "partial", "cancelled")) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($run.status -ne "indexed") { throw "Document ingestion ended as $($run.status): $($run.error_message)" }
    $status = Invoke-RestMethod "$BaseUrl/documents/$($document.document_id)/status"
    $rag = Invoke-RestMethod -Method Post "$BaseUrl/rag/chat" -ContentType "application/json" -Body (@{message="Summarize this document.";document_id=$document.document_id} | ConvertTo-Json)
    Write-Host "Index: $($run.status), version: $($run.index_version), chunks: $($status.chunks_count), sources: $($rag.sources.Count)"
}

Write-Host "Smoke test completed."
