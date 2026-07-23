param(
  [string]$OutputDir = "D:\LearnNote\analysis\marketing-case"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$output = [System.IO.Path]::GetFullPath($OutputDir)
$slidesDir = Join-Path $output "slides"
$audioDir = Join-Path $output "audio"
$clipsDir = Join-Path $output "clips"

New-Item -ItemType Directory -Force -Path $output, $slidesDir, $audioDir, $clipsDir | Out-Null
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Speech

$segments = @(
  @{
    Title = "梯度下降与学习率"
    Kicker = "01 · 学习目标"
    Lines = @("理解参数如何沿损失下降", "比较过小、合适和过大的学习率", "掌握三步调参检查法")
    Voice = "这节微课用一个简单的损失曲线，理解梯度下降为什么能够优化模型，以及学习率为什么会决定训练是否稳定。"
    Accent = "#0A8F8A"
  },
  @{
    Title = "先找到下降方向"
    Kicker = "02 · 梯度的含义"
    Lines = @("横轴：模型参数 theta", "纵轴：损失函数 L(theta)", "梯度指向上升最快的方向")
    Voice = "把横轴看作模型参数，纵轴看作损失。梯度给出损失上升最快的方向，因此更新参数时要沿梯度的反方向移动。"
    Accent = "#2563D9"
  },
  @{
    Title = "一次参数更新"
    Kicker = "03 · 核心公式"
    Lines = @("theta(new) = theta(old) - eta * gradient", "eta 是学习率", "gradient 决定方向，eta 决定步长")
    Voice = "核心公式是，新参数等于旧参数减去学习率乘以梯度。梯度决定往哪里走，学习率 eta 决定每一步走多远。"
    Accent = "#0A8F8A"
  },
  @{
    Title = "学习率过小"
    Kicker = "04 · 常见问题"
    Lines = @("损失能够下降，但速度很慢", "训练轮数增加，计算成本上升", "曲线表现为平缓而持续的下降")
    Voice = "如果学习率过小，损失通常能够下降，但每一步都很短，训练会非常慢。曲线看起来平稳，却需要更多轮次才能接近最优点。"
    Accent = "#D58A24"
  },
  @{
    Title = "学习率过大"
    Kicker = "05 · 常见问题"
    Lines = @("更新跨过最低点并来回震荡", "损失可能突然升高或发散", "先降低学习率，再检查数据尺度")
    Voice = "如果学习率过大，参数会跨过最低点，在两侧来回震荡，严重时损失直接发散。此时应先降低学习率，再检查特征尺度和梯度是否异常。"
    Accent = "#D95C5C"
  },
  @{
    Title = "三步完成调参"
    Kicker = "06 · 复习清单"
    Lines = @("一，看损失是否持续下降", "二，比较不同学习率的收敛速度", "三，保留验证集最优的模型参数")
    Voice = "最后记住三步。第一，看损失是否持续下降。第二，比较不同学习率的收敛速度。第三，保留验证集表现最好的模型参数。"
    Accent = "#2563D9"
  }
)

function New-Slide {
  param(
    [hashtable]$Segment,
    [int]$Index,
    [string]$Path
  )

  $bitmap = [System.Drawing.Bitmap]::new(1280, 720)
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
  $graphics.Clear([System.Drawing.ColorTranslator]::FromHtml("#F7FBFC"))

  $ink = [System.Drawing.ColorTranslator]::FromHtml("#10212A")
  $muted = [System.Drawing.ColorTranslator]::FromHtml("#5E7078")
  $line = [System.Drawing.ColorTranslator]::FromHtml("#D8E5E8")
  $accent = [System.Drawing.ColorTranslator]::FromHtml($Segment.Accent)
  $white = [System.Drawing.Color]::White

  $graphics.FillRectangle([System.Drawing.SolidBrush]::new($ink), 0, 0, 1280, 86)
  $graphics.FillRectangle([System.Drawing.SolidBrush]::new($accent), 0, 86, 18, 634)

  $brandFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 22, [System.Drawing.FontStyle]::Bold)
  $kickerFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 18, [System.Drawing.FontStyle]::Bold)
  $titleFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 44, [System.Drawing.FontStyle]::Bold)
  $bodyFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 24, [System.Drawing.FontStyle]::Regular)
  $smallFont = [System.Drawing.Font]::new("Microsoft YaHei UI", 16, [System.Drawing.FontStyle]::Regular)

  $graphics.DrawString("LearnNote 微课", $brandFont, [System.Drawing.SolidBrush]::new($white), 48, 24)
  $graphics.DrawString($Segment.Kicker, $kickerFont, [System.Drawing.SolidBrush]::new($accent), 72, 126)
  $graphics.DrawString($Segment.Title, $titleFont, [System.Drawing.SolidBrush]::new($ink), 68, 174)

  $panelBrush = [System.Drawing.SolidBrush]::new($white)
  $graphics.FillRectangle($panelBrush, 68, 278, 1140, 326)
  $graphics.DrawRectangle([System.Drawing.Pen]::new($line, 2), 68, 278, 1140, 326)

  $y = 322
  foreach ($lineText in $Segment.Lines) {
    $graphics.FillEllipse([System.Drawing.SolidBrush]::new($accent), 104, $y + 10, 13, 13)
    $graphics.DrawString($lineText, $bodyFont, [System.Drawing.SolidBrush]::new($ink), 142, $y)
    $y += 82
  }

  $graphics.DrawString(("演示课程 · 第 {0}/6 页" -f $Index), $smallFont, [System.Drawing.SolidBrush]::new($muted), 72, 650)
  $graphics.DrawString("用于验证转写、视觉切片与证据化笔记", $smallFont, [System.Drawing.SolidBrush]::new($muted), 730, 650)

  $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  $graphics.Dispose()
  $bitmap.Dispose()
}

$ffmpeg = & $python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
if (-not (Test-Path -LiteralPath $ffmpeg -PathType Leaf)) {
  throw "ffmpeg was not found through imageio-ffmpeg."
}

$synth = [System.Speech.Synthesis.SpeechSynthesizer]::new()
$synth.SelectVoice("Microsoft Huihui Desktop")
$synth.Rate = -1
$concatLines = @()
$transcript = @()
$cursor = 0.0

for ($index = 0; $index -lt $segments.Count; $index++) {
  $number = $index + 1
  $segment = $segments[$index]
  $slide = Join-Path $slidesDir ("slide-{0:D2}.png" -f $number)
  $wav = Join-Path $audioDir ("segment-{0:D2}.wav" -f $number)
  $clip = Join-Path $clipsDir ("segment-{0:D2}.mp4" -f $number)

  New-Slide -Segment $segment -Index $number -Path $slide
  $synth.SetOutputToWaveFile($wav)
  $synth.Speak($segment.Voice)
  $synth.SetOutputToNull()

  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $probe = (& $ffmpeg -hide_banner -i $wav 2>&1 | Out-String)
  $ErrorActionPreference = $previousErrorAction
  if ($probe -notmatch "Duration:\s*(\d+):(\d+):([\d.]+)") {
    throw "Could not determine WAV duration: $wav"
  }
  $duration = [int]$Matches[1] * 3600 + [int]$Matches[2] * 60 + [double]$Matches[3]
  $end = $cursor + $duration
  $transcript += [pscustomobject]@{
    start = [math]::Round($cursor, 2)
    end = [math]::Round($end, 2)
    text = $segment.Voice
  }
  $cursor = $end

  & $ffmpeg -y -hide_banner -loglevel error -loop 1 -framerate 30 -i $slide -i $wav `
    -vf "scale=1280:720,format=yuv420p" -c:v libx264 -preset veryfast -tune stillimage `
    -c:a aac -b:a 128k -shortest -movflags +faststart $clip
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to build clip $number."
  }
  $concatLines += "file '$($clip.Replace('\', '/'))'"
}

$synth.Dispose()
$concatPath = Join-Path $output "concat.txt"
$videoPath = Join-Path $output "gradient-descent-learning-rate.mp4"
$transcriptPath = Join-Path $output "expected-transcript.json"
$concatLines | Set-Content -LiteralPath $concatPath -Encoding ascii
$transcript | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $transcriptPath -Encoding utf8

& $ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i $concatPath -c copy -movflags +faststart $videoPath
if ($LASTEXITCODE -ne 0) {
  throw "Failed to concatenate the marketing case video."
}

[pscustomobject]@{
  video = $videoPath
  expected_transcript = $transcriptPath
  duration_seconds = [math]::Round($cursor, 2)
  segments = $segments.Count
  bytes = (Get-Item -LiteralPath $videoPath).Length
} | ConvertTo-Json -Depth 4
