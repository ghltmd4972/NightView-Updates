using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Reflection;
using System.Text.Json;

namespace AnimePickerNative;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, e) => ShowFatal(e.Exception);
        AppDomain.CurrentDomain.UnhandledException += (_, e) =>
        {
            if (e.ExceptionObject is Exception ex) ShowFatal(ex);
        };

        try
        {
            Application.Run(new MainForm());
        }
        catch (Exception ex)
        {
            ShowFatal(ex);
        }
    }

    private static void ShowFatal(Exception ex)
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AnimeCharacterRandomPickerNative");
            Directory.CreateDirectory(dir);
            File.AppendAllText(
                Path.Combine(dir, "native_error.log"),
                $"{DateTimeOffset.Now:O} {ex}\r\n");
        }
        catch { }

        try
        {
            MessageBox.Show(
                "프로그램 실행 중 오류가 발생했습니다.\r\n\r\n" + ex.Message,
                "애니 캐릭터 랜덤 추첨기",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
        catch { }
    }
}

internal sealed class MainForm : Form
{
    private readonly WebView2 _webView;
    private readonly NativeBackend _backend;
    private readonly NativeHttpServer _server;
    private readonly string _webViewDataDir;
    private readonly string _stateDir;
    private readonly string _windowStatePath;

    public MainForm()
    {
        Text = "애니 캐릭터 랜덤 추첨기 — 최신 업데이트 완료 · v67";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 1280;
        Height = 900;
        MinimumSize = new Size(900, 640);

        _stateDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AnimeCharacterRandomPickerV36");
        Directory.CreateDirectory(_stateDir);
        _windowStatePath = Path.Combine(_stateDir, "window_state.json");
        RestoreWindowState();

        _webView = new WebView2
        {
            Dock = DockStyle.Fill
        };
        Controls.Add(_webView);

        _backend = new NativeBackend(_stateDir, SelectLinkedFile);
        _server = new NativeHttpServer(ReadEmbeddedPickerHtml(), _backend);
        _server.Start();

        _webViewDataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "AnimeCharacterRandomPickerWebView2");

        Shown += async (_, _) => await InitializeWebViewAsync();
        FormClosing += (_, _) => SaveWindowState();
        FormClosed += (_, _) => _server.Dispose();
    }

    private void RestoreWindowState()
    {
        try
        {
            if (!File.Exists(_windowStatePath)) return;

            var state = JsonSerializer.Deserialize<WindowStateData>(
                File.ReadAllText(_windowStatePath));
            if (state is null) return;

            var bounds = new Rectangle(
                state.X,
                state.Y,
                Math.Max(MinimumSize.Width, state.Width),
                Math.Max(MinimumSize.Height, state.Height));

            if (!Screen.AllScreens.Any(screen => screen.WorkingArea.IntersectsWith(bounds))) return;

            StartPosition = FormStartPosition.Manual;
            Bounds = bounds;
            if (state.Maximized) WindowState = FormWindowState.Maximized;
        }
        catch
        {
            StartPosition = FormStartPosition.CenterScreen;
        }
    }

    private void SaveWindowState()
    {
        try
        {
            Directory.CreateDirectory(_stateDir);
            var bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
            var state = new WindowStateData
            {
                X = bounds.X,
                Y = bounds.Y,
                Width = bounds.Width,
                Height = bounds.Height,
                Maximized = WindowState == FormWindowState.Maximized
            };

            File.WriteAllText(
                _windowStatePath,
                JsonSerializer.Serialize(state));
        }
        catch { }
    }

    private sealed class WindowStateData
    {
        public int X { get; set; }
        public int Y { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public bool Maximized { get; set; }
    }

    private static byte[] ReadEmbeddedPickerHtml()
    {
        using var stream = Assembly.GetExecutingAssembly()
            .GetManifestResourceStream("AnimePickerNative.picker.html")
            ?? throw new InvalidOperationException("내장 UI를 찾지 못했습니다.");
        using var ms = new MemoryStream();
        stream.CopyTo(ms);
        return ms.ToArray();
    }

    private async Task InitializeWebViewAsync()
    {
        try
        {
            Directory.CreateDirectory(_webViewDataDir);
            var environment = await CoreWebView2Environment.CreateAsync(
                browserExecutableFolder: null,
                userDataFolder: _webViewDataDir);

            await _webView.EnsureCoreWebView2Async(environment);

            var settings = _webView.CoreWebView2.Settings;
            settings.IsStatusBarEnabled = false;
            settings.AreDefaultContextMenusEnabled = true;
            settings.AreDevToolsEnabled = false;
            settings.IsZoomControlEnabled = true;
            settings.IsBuiltInErrorPageEnabled = true;

            _webView.CoreWebView2.Navigate(_server.BaseUrl);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "WebView2 초기화에 실패했습니다.\r\n\r\n" + ex.Message,
                "애니 캐릭터 랜덤 추첨기",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            Close();
        }
    }

    private string? SelectLinkedFile(string kind)
    {
        if (InvokeRequired)
        {
            return (string?)Invoke(new Func<string, string?>(SelectLinkedFile), kind);
        }

        using var dialog = new OpenFileDialog
        {
            Title = kind == "character" ? "캐릭터 TXT 파일 선택" : "표정 TXT 파일 선택",
            Filter = "텍스트 파일 (*.txt)|*.txt|모든 파일 (*.*)|*.*",
            Multiselect = false,
            RestoreDirectory = true,
            CheckFileExists = true
        };

        return dialog.ShowDialog(this) == DialogResult.OK
            ? dialog.FileName
            : null;
    }
}
