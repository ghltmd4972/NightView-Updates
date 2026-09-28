using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AnimePickerNative;

internal sealed class NativeHttpServer : IDisposable
{
    private readonly byte[] _pickerHtml;
    private readonly NativeBackend _backend;
    private readonly CancellationTokenSource _cts = new();
    private TcpListener? _listener;
    private Task? _acceptLoop;

    public string BaseUrl { get; private set; } = "";

    public NativeHttpServer(byte[] pickerHtml, NativeBackend backend)
    {
        _pickerHtml = pickerHtml;
        _backend = backend;
    }

    public void Start()
    {
        _listener = new TcpListener(IPAddress.Loopback, 0);
        _listener.Start();
        var port = ((IPEndPoint)_listener.LocalEndpoint).Port;
        BaseUrl = $"http://127.0.0.1:{port}/";
        _acceptLoop = Task.Run(() => AcceptLoopAsync(_cts.Token));
    }

    private async Task AcceptLoopAsync(CancellationToken token)
    {
        while (!token.IsCancellationRequested)
        {
            TcpClient? client = null;
            try
            {
                client = await _listener!.AcceptTcpClientAsync(token);
                _ = Task.Run(() => HandleClientAsync(client, token), token);
            }
            catch (OperationCanceledException)
            {
                client?.Dispose();
                break;
            }
            catch
            {
                client?.Dispose();
                if (!token.IsCancellationRequested)
                    await Task.Delay(50, token).ContinueWith(_ => { }, CancellationToken.None);
            }
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken token)
    {
        using (client)
        {
            try
            {
                client.NoDelay = true;
                using var stream = client.GetStream();
                var request = await ReadRequestAsync(stream, token);
                if (request is null) return;

                var response = await DispatchAsync(request);
                await WriteResponseAsync(stream, response, token);
            }
            catch
            {
                // Local UI endpoint: silently drop malformed/aborted requests.
            }
        }
    }

    private async Task<HttpResponse> DispatchAsync(HttpRequest request)
    {
        var path = request.Path;

        if (request.Method == "GET" && (path == "/" || path == "/index.html" || path == "/picker.html"))
            return HttpResponse.Bytes(200, "text/html; charset=utf-8", _pickerHtml);

        if (path == "/favicon.ico")
            return HttpResponse.Empty(204);

        if (path == "/__heartbeat")
            return HttpResponse.Empty(204);

        if (request.Method == "GET" && path == "/api/health")
            return HttpResponse.Json(200, _backend.GetHealth());

        if (path.StartsWith("/api/state/", StringComparison.Ordinal))
        {
            var name = Uri.UnescapeDataString(path["/api/state/".Length..]);
            if (!Regex.IsMatch(name, "^[A-Za-z0-9_-]{1,64}$"))
                return HttpResponse.Text(400, "invalid state name");

            if (request.Method == "GET")
            {
                var data = _backend.LoadState(name);
                return data is null
                    ? HttpResponse.Empty(204)
                    : HttpResponse.Bytes(200, "application/json; charset=utf-8", data);
            }

            if (request.Method == "POST")
            {
                _backend.SaveState(name, request.Body);
                return HttpResponse.Json(200, new { ok = true });
            }
        }

        if (request.Method == "POST" && path == "/api/character-file/select")
            return LinkedFileResponse(_backend.SelectAndRemember("character"));

        if (request.Method == "POST" && path == "/api/expression-file/select")
            return LinkedFileResponse(_backend.SelectAndRemember("expression"));

        if (request.Method == "GET" && path == "/api/character-file/reload")
            return LinkedFileResponse(_backend.ReloadLinked("character"));

        if (request.Method == "GET" && path == "/api/expression-file/reload")
            return LinkedFileResponse(_backend.ReloadLinked("expression"));

        return HttpResponse.Text(404, "not found");
    }

    private static HttpResponse LinkedFileResponse(LinkedFileResult result)
    {
        return result.Status switch
        {
            LinkedFileStatus.None => HttpResponse.Empty(204),
            LinkedFileStatus.Ok => HttpResponse.Json(200, new
            {
                raw = result.Raw,
                fileName = result.FileName,
                size = result.Size,
                lastModified = result.LastModified
            }),
            _ => HttpResponse.Text(404, result.Error ?? "연결된 TXT 파일을 찾을 수 없습니다.")
        };
    }

    private static async Task<HttpRequest?> ReadRequestAsync(NetworkStream stream, CancellationToken token)
    {
        const int maxHeaderBytes = 64 * 1024;
        var headerBytes = new List<byte>(1024);
        int matched = 0;

        while (headerBytes.Count < maxHeaderBytes)
        {
            var one = new byte[1];
            var read = await stream.ReadAsync(one, token);
            if (read <= 0) return null;
            var b = one[0];
            headerBytes.Add(b);

            matched = (matched, b) switch
            {
                (0, 13) => 1,
                (1, 10) => 2,
                (2, 13) => 3,
                (3, 10) => 4,
                (_, 13) => 1,
                _ => 0
            };

            if (matched == 4) break;
        }

        if (matched != 4) return null;

        var headerText = Encoding.ASCII.GetString(headerBytes.ToArray());
        var lines = headerText.Split(new[] { "\r\n" }, StringSplitOptions.None);
        if (lines.Length == 0) return null;

        var first = lines[0].Split(' ', 3);
        if (first.Length < 2) return null;

        var method = first[0].ToUpperInvariant();
        var target = first[1];
        var headers = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        for (int i = 1; i < lines.Length; i++)
        {
            var line = lines[i];
            if (string.IsNullOrEmpty(line)) break;
            var colon = line.IndexOf(':');
            if (colon <= 0) continue;
            headers[line[..colon].Trim()] = line[(colon + 1)..].Trim();
        }

        var contentLength = 0;
        if (headers.TryGetValue("Content-Length", out var value))
            int.TryParse(value, out contentLength);

        if (contentLength < 0 || contentLength > 16 * 1024 * 1024)
            return null;

        var body = new byte[contentLength];
        var offset = 0;
        while (offset < body.Length)
        {
            var read = await stream.ReadAsync(body.AsMemory(offset), token);
            if (read <= 0) return null;
            offset += read;
        }

        string path;
        try
        {
            var uri = new Uri("http://127.0.0.1" + target);
            path = uri.AbsolutePath;
        }
        catch
        {
            path = target.Split('?', 2)[0];
        }

        return new HttpRequest(method, path, headers, body);
    }

    private static async Task WriteResponseAsync(NetworkStream stream, HttpResponse response, CancellationToken token)
    {
        var reason = response.StatusCode switch
        {
            200 => "OK",
            204 => "No Content",
            400 => "Bad Request",
            404 => "Not Found",
            _ => "Error"
        };

        var header = new StringBuilder();
        header.Append($"HTTP/1.1 {response.StatusCode} {reason}\r\n");
        header.Append("Connection: close\r\n");
        header.Append("Cache-Control: no-store\r\n");
        header.Append("X-Content-Type-Options: nosniff\r\n");
        if (!string.IsNullOrEmpty(response.ContentType))
            header.Append($"Content-Type: {response.ContentType}\r\n");
        header.Append($"Content-Length: {response.Body.Length}\r\n\r\n");

        var headerBytes = Encoding.ASCII.GetBytes(header.ToString());
        await stream.WriteAsync(headerBytes, token);
        if (response.Body.Length > 0)
            await stream.WriteAsync(response.Body, token);
        await stream.FlushAsync(token);
    }

    public void Dispose()
    {
        try { _cts.Cancel(); } catch { }
        try { _listener?.Stop(); } catch { }
        try { _acceptLoop?.Wait(300); } catch { }
        _cts.Dispose();
    }

    private sealed record HttpRequest(
        string Method,
        string Path,
        Dictionary<string, string> Headers,
        byte[] Body);

    private sealed record HttpResponse(int StatusCode, string? ContentType, byte[] Body)
    {
        public static HttpResponse Empty(int status)
            => new(status, null, Array.Empty<byte>());

        public static HttpResponse Text(int status, string text)
            => new(status, "text/plain; charset=utf-8", Encoding.UTF8.GetBytes(text));

        public static HttpResponse Bytes(int status, string contentType, byte[] body)
            => new(status, contentType, body);

        public static HttpResponse Json(int status, object value)
            => new(status, "application/json; charset=utf-8",
                JsonSerializer.SerializeToUtf8Bytes(value));
    }
}

internal enum LinkedFileStatus
{
    None,
    Ok,
    Error
}

internal sealed record LinkedFileResult(
    LinkedFileStatus Status,
    string? Raw = null,
    string? FileName = null,
    long Size = 0,
    long LastModified = 0,
    string? Error = null);

internal sealed class NativeBackend
{
    private readonly string _stateDir;
    private readonly Func<string, string?> _filePicker;
    private readonly object _ioLock = new();

    public NativeBackend(string stateDir, Func<string, string?> filePicker)
    {
        _stateDir = stateDir;
        _filePicker = filePicker;
        Directory.CreateDirectory(_stateDir);
    }

    public byte[]? LoadState(string name)
    {
        var path = StatePath(name);
        lock (_ioLock)
        {
            return File.Exists(path) ? File.ReadAllBytes(path) : null;
        }
    }

    public void SaveState(string name, byte[] body)
    {
        var path = StatePath(name);
        var temp = path + ".tmp";
        var backup = path + ".bak";

        lock (_ioLock)
        {
            Directory.CreateDirectory(_stateDir);
            File.WriteAllBytes(temp, body);

            if (File.Exists(path))
                File.Copy(path, backup, overwrite: true);

            File.Move(temp, path, overwrite: true);
        }
    }

    public LinkedFileResult SelectAndRemember(string kind)
    {
        var selected = _filePicker(kind);
        if (string.IsNullOrWhiteSpace(selected))
            return new LinkedFileResult(LinkedFileStatus.None);

        lock (_ioLock)
        {
            File.WriteAllText(
                LinkedPathFile(kind),
                JsonSerializer.Serialize(selected),
                new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
        }

        return ReadLinkedFile(selected);
    }

    public LinkedFileResult ReloadLinked(string kind)
    {
        var linked = ReadRememberedPath(kind);
        if (string.IsNullOrWhiteSpace(linked))
            return new LinkedFileResult(LinkedFileStatus.None);

        return ReadLinkedFile(linked);
    }

    public object GetHealth()
    {
        var items = new List<object>();

        var stateOk = false;
        var stateDetail = _stateDir;
        try
        {
            Directory.CreateDirectory(_stateDir);
            var probe = Path.Combine(_stateDir, ".health_probe");
            File.WriteAllText(probe, "ok");
            File.Delete(probe);
            stateOk = true;
        }
        catch (Exception ex)
        {
            stateDetail = ex.Message;
        }

        items.Add(new { name = "영구 저장 폴더", ok = stateOk, detail = stateDetail });
        items.Add(LinkedHealth("character", "캐릭터 TXT 연결"));
        items.Add(LinkedHealth("expression", "표정 TXT 연결"));
        items.Add(new { name = "로컬 UI 서버", ok = true, detail = "정상" });

        return new
        {
            ok = stateOk,
            items
        };
    }

    private object LinkedHealth(string kind, string name)
    {
        try
        {
            var path = ReadRememberedPath(kind);
            if (string.IsNullOrWhiteSpace(path))
                return new { name, ok = true, detail = "연결 없음" };

            var exists = File.Exists(path);
            return new
            {
                name,
                ok = exists,
                detail = exists ? path : "연결된 파일을 찾을 수 없음: " + path
            };
        }
        catch (Exception ex)
        {
            return new { name, ok = false, detail = ex.Message };
        }
    }

    private LinkedFileResult ReadLinkedFile(string path)
    {
        try
        {
            if (!File.Exists(path))
                return new LinkedFileResult(
                    LinkedFileStatus.Error,
                    Error: "연결된 TXT 파일을 찾을 수 없습니다.");

            var info = new FileInfo(path);
            var raw = File.ReadAllText(path, Encoding.UTF8);
            var modified = new DateTimeOffset(info.LastWriteTimeUtc).ToUnixTimeMilliseconds();

            return new LinkedFileResult(
                LinkedFileStatus.Ok,
                Raw: raw,
                FileName: info.Name,
                Size: info.Length,
                LastModified: modified);
        }
        catch (Exception ex)
        {
            return new LinkedFileResult(LinkedFileStatus.Error, Error: ex.Message);
        }
    }

    private string? ReadRememberedPath(string kind)
    {
        var pathFile = LinkedPathFile(kind);
        lock (_ioLock)
        {
            if (!File.Exists(pathFile)) return null;
            var json = File.ReadAllText(pathFile, Encoding.UTF8);
            return JsonSerializer.Deserialize<string>(json);
        }
    }

    private string StatePath(string name)
        => Path.Combine(_stateDir, $"state_{name}.json");

    private string LinkedPathFile(string kind)
        => Path.Combine(
            _stateDir,
            kind == "character" ? "linked_character.json" : "linked_expression.json");
}
