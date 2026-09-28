using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Reflection;

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

    public MainForm()
    {
        Text = "애니 캐릭터 랜덤 추첨기";
        StartPosition = FormStartPosition.CenterScreen;
        Width = 1280;
        Height = 900;
        MinimumSize = new Size(900, 640);

        _webView = new WebView2
        {
            Dock = DockStyle.Fill
        };
        Controls.Add(_webView);

        var stateDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "AnimeCharacterRandomPickerV36");

        _backend = new NativeBackend(stateDir, SelectLinkedFile);
        _server = new NativeHttpServer(ReadEmbeddedPickerHtml(), _backend);
        _server.Start();

        _webViewDataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "AnimeCharacterRandomPickerWebView2");

        Shown += async (_, _) => await InitializeWebViewAsync();
        FormClosed += (_, _) => _server.Dispose();
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
