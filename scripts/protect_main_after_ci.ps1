param(
  [Parameter(Mandatory=$true)][string]$Owner,
  [string]$Repository = "e2eproof"
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw "GitHub CLI is required."
}

gh auth status
if ($LASTEXITCODE -ne 0) { throw "Run gh auth login first." }

$repo = "$Owner/$Repository"
$body = @{
  required_status_checks = @{
    strict = $true
    contexts = @("quality-gate", "browser-gate", "action-self-test")
  }
  enforce_admins = $false
  required_pull_request_reviews = $null
  restrictions = $null
  required_linear_history = $true
  allow_force_pushes = $false
  allow_deletions = $false
} | ConvertTo-Json -Depth 6

$temp = New-TemporaryFile
Set-Content -Path $temp -Value $body -Encoding utf8
gh api -X PUT "repos/$repo/branches/main/protection" `
  -H "Accept: application/vnd.github+json" `
  --input $temp
Remove-Item $temp

Write-Host "Protected main branch with required release gates." -ForegroundColor Green
