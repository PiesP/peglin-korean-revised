#nullable enable
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using BepInEx;
using I2.Loc;
using PeglinKoreanRevised;
using UnityEngine.SceneManagement;

static class Program
{
    private sealed class FakePort : ILocalizationPort
    {
        internal readonly object Source = new();
        internal bool Available = true;
        internal int MatchCount;
        internal int InitializeCount;
        internal int ApplyCount;
        internal int BindCount;
        internal int LocalizeCount;
        internal int DisposeCount;
        internal Action<object, bool>? Callback;

        public void Initialize() => InitializeCount++;
        public IEnumerable<object> Sources() => Available ? new[] { Source } : Array.Empty<object>();
        public int Apply(object source, IReadOnlyDictionary<string, string> terms,
            bool logMissing, Action<object, bool> callback)
        {
            Require(ReferenceEquals(Source, source), "source identity changed");
            Require(terms.Count == 1 && terms["term"] == "translated", "terms changed");
            ApplyCount++;
            if (Callback == null) { Callback = callback; BindCount++; }
            return MatchCount;
        }
        public void LocalizeAll() => LocalizeCount++;
        public void Dispose() { DisposeCount++; Callback = null; }
        internal void Update(bool receivedNewData) => Callback?.Invoke(Source, receivedNewData);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    private static int Drain(IEnumerator iterator)
    {
        int yields = 0;
        while (iterator.MoveNext()) yields++;
        return yields;
    }

    private static OverlaySession Make(FakePort port, List<string> info, List<string> error) =>
        new(new Dictionary<string, string> { ["term"] = "translated" },
            port, info.Add, error.Add);

    private static OverlaySession Make(I2LocalizationAdapter adapter, List<string> info,
        List<string> error) => new(new Dictionary<string, string> { ["term"] = "translated" },
            adapter, info.Add, error.Add);

    private static void SessionCases()
    {
        var info = new List<string>();
        var errors = new List<string>();
        var missing = new FakePort { Available = false };
        var missingSession = Make(missing, info, errors);
        Require(Drain(missingSession.ApplyInitially()) == 300, "missing-source deadline");
        Require(missing.InitializeCount == 300 && errors.Count == 1, "missing-source outcome");
        missingSession.Dispose();

        info.Clear(); errors.Clear();
        var zero = new FakePort { MatchCount = 0 };
        var zeroSession = Make(zero, info, errors);
        Require(Drain(zeroSession.ApplyInitially()) == 300, "zero-match deadline");
        Require(zero.BindCount == 1 && zero.ApplyCount == 300, "zero-match identity/binding");
        Require(zero.LocalizeCount == 0 && errors.Count == 1, "zero-match result");
        zeroSession.Dispose();

        info.Clear(); errors.Clear();
        var positive = new FakePort { MatchCount = 1 };
        var session = Make(positive, info, errors);
        Require(Drain(session.ApplyInitially()) == 29, "initial stable-frame bound");
        Require(positive.InitializeCount == 30 && positive.ApplyCount == 1, "initial one-shot apply");
        Require(positive.BindCount == 1 && positive.LocalizeCount == 1, "initial bind/localize");
        Require(info.Count == 1 && errors.Count == 0, "initial diagnostics");
        positive.Update(false);
        Require(positive.ApplyCount == 1, "unsuccessful update must be inert");
        positive.Update(true);
        Require(positive.ApplyCount == 2 && positive.LocalizeCount == 2, "successful update must reapply");
        Require(Drain(session.ApplyAfterSceneLoad()) == 30, "scene poll bound");
        Require(positive.ApplyCount == 2, "scene should not reapply known source");
        var oldCallback = positive.Callback;
        session.Dispose(); session.Dispose();
        Require(positive.DisposeCount == 1, "owned disposal must be idempotent");
        oldCallback?.Invoke(positive.Source, true);
        Require(positive.ApplyCount == 2, "late callback must be inert");
        Require(Drain(session.ApplyAfterSceneLoad()) == 0, "retired scene work must be inert");
    }

    private static void AdapterCases()
    {
        var info = new List<string>();
        var errors = new List<string>();
        LocalizationManager.Reset();
        var absent = Make(new I2LocalizationAdapter(_ => { }), info, errors);
        Require(Drain(absent.ApplyInitially()) == 300, "absent I2 source deadline");
        Require(LocalizationManager.InitializeCount == 300 && errors.Count == 1,
            "absent I2 source result");
        absent.Dispose();

        info.Clear(); errors.Clear();
        LocalizationManager.Reset();
        var noKorean = new LanguageSourceData { HasKorean = false };
        noKorean.Terms.Add("term", new TermData());
        LocalizationManager.Sources = new List<LanguageSourceData> { noKorean };
        var noKoreanSession = Make(new I2LocalizationAdapter(_ => { }), info, errors);
        Require(Drain(noKoreanSession.ApplyInitially()) == 300, "no-Korean deadline");
        Require(noKorean.SubscribeCount == 0 && noKorean.Terms["term"].Writes == 0 &&
            LocalizationManager.LocalizeCount == 0 && errors.Count == 1,
            "no-Korean source must remain untouched");
        noKoreanSession.Dispose();

        info.Clear(); errors.Clear();
        LocalizationManager.Reset();
        var zero = new LanguageSourceData();
        LocalizationManager.Sources = new List<LanguageSourceData> { zero };
        var zeroSession = Make(new I2LocalizationAdapter(_ => { }), info, errors);
        Require(Drain(zeroSession.ApplyInitially()) == 300, "zero-match I2 deadline");
        Require(zero.SubscribeCount == 1 && LocalizationManager.LocalizeCount == 0 &&
            errors.Count == 1, "zero-match source must subscribe once without relocalizing");
        zeroSession.Dispose(); zeroSession.Dispose();
        Require(zero.UnsubscribeCount == 1, "zero-match source must unsubscribe once");

        info.Clear(); errors.Clear();
        LocalizationManager.Reset();
        var updatedSource = new LanguageSourceData();
        LocalizationManager.Sources = new List<LanguageSourceData> { updatedSource };
        var updatedSession = Make(new I2LocalizationAdapter(_ => { }), info, errors);
        var updatedInitial = updatedSession.ApplyInitially();
        Require(updatedInitial.MoveNext() && updatedSource.SubscribeCount == 1,
            "initial polling must subscribe before a matching term arrives");
        var updatedTerm = new TermData();
        updatedSource.Terms.Add("term", updatedTerm);
        updatedSource.RaiseUpdate(true);
        Require(updatedTerm.Writes == 1 && updatedTerm.Translation == "translated" &&
            LocalizationManager.LocalizeCount == 1,
            "I2 update during initial polling must apply the first translation");
        Require(Drain(updatedInitial) == 29 && errors.Count == 0 &&
            info.Exists(message => message.Contains("Reapplied 1 Korean translations")) &&
            updatedTerm.Writes == 1 && updatedSource.SubscribeCount == 1,
            "initial completion must retain a successful I2 update without a false no-match error");
        updatedSession.Dispose();
        Require(updatedSource.UnsubscribeCount == 1, "updated source must unsubscribe once");

        info.Clear(); errors.Clear();
        LocalizationManager.Reset();
        var sceneInitialSource = new LanguageSourceData();
        LocalizationManager.Sources = new List<LanguageSourceData> { sceneInitialSource };
        var sceneInitialSession = Make(new I2LocalizationAdapter(_ => { }), info, errors);
        var sceneInitial = sceneInitialSession.ApplyInitially();
        Require(sceneInitial.MoveNext() && sceneInitialSource.SubscribeCount == 1,
            "initial polling must subscribe before the scene adds a matching source");
        var firstSceneSource = new LanguageSourceData();
        var firstSceneTerm = new TermData();
        firstSceneSource.Terms.Add("term", firstSceneTerm);
        LocalizationManager.Sources.Add(firstSceneSource);
        var sceneDuringInitial = sceneInitialSession.ApplyAfterSceneLoad();
        Require(sceneDuringInitial.MoveNext() && firstSceneTerm.Writes == 1 &&
            firstSceneTerm.Translation == "translated" && LocalizationManager.LocalizeCount == 1,
            "scene polling must apply the first translation while initial polling waits");
        Require(Drain(sceneInitial) == 29 && errors.Count == 0 &&
            info.Exists(message => message.Contains("Applied 1 Korean translations to a newly loaded")) &&
            firstSceneTerm.Writes == 1,
            "initial completion must retain scene success without a false no-match error");
        Require(Drain(sceneDuringInitial) == 29 && firstSceneTerm.Writes == 1,
            "remaining scene polling must not duplicate the application");
        sceneInitialSession.Dispose();
        Require(sceneInitialSource.UnsubscribeCount == 1 && firstSceneSource.UnsubscribeCount == 1,
            "scene and initial source subscriptions must retire once");

        info.Clear(); errors.Clear();
        LocalizationManager.Reset();
        var source = new LanguageSourceData();
        var term = new TermData();
        source.Terms.Add("term", term);
        LocalizationManager.Sources = null;
        LocalizationManager.OnInitialize = frame =>
        {
            if (frame == 41) LocalizationManager.Sources = new List<LanguageSourceData> { source };
        };
        var adapter = new I2LocalizationAdapter(_ => { });
        var session = Make(adapter, info, errors);
        Require(Drain(session.ApplyInitially()) == 69, "delayed arrival stable-frame deadline");
        Require(LocalizationManager.InitializeCount == 70 && term.Writes == 1 &&
            term.Translation == "translated" && source.SubscribeCount == 1 &&
            LocalizationManager.LocalizeCount == 1 && info.Count == 1 && errors.Count == 0,
            "delayed source must receive one owned application");
        source.RaiseUpdate(false);
        Require(term.Writes == 1 && LocalizationManager.LocalizeCount == 1,
            "unsuccessful I2 update must leave translation alone");
        source.RaiseUpdate(true);
        Require(term.Writes == 2 && LocalizationManager.LocalizeCount == 2 &&
            source.SubscribeCount == 1, "successful I2 update must reapply without resubscribing");
        var sceneSource = new LanguageSourceData();
        var sceneTerm = new TermData();
        sceneSource.Terms.Add("term", sceneTerm);
        LocalizationManager.Sources!.Add(sceneSource);
        Require(Drain(session.ApplyAfterSceneLoad()) == 30, "scene source poll bound");
        Require(term.Writes == 2 && sceneTerm.Writes == 1 &&
            sceneSource.SubscribeCount == 1 && LocalizationManager.LocalizeCount == 3,
            "scene must apply only a new source identity");
        session.Dispose(); session.Dispose();
        Require(source.UnsubscribeCount == 1 && sceneSource.UnsubscribeCount == 1,
            "owned adapter disposal must unsubscribe each source once");
        source.RaiseUpdate(true);
        sceneSource.RaiseUpdate(true);
        Require(term.Writes == 2 && sceneTerm.Writes == 1,
            "retired I2 callbacks must not write");

        LocalizationManager.Reset();
        var partialSource = new LanguageSourceData();
        var partialTerm = new TermData();
        partialSource.Terms.Add("term", partialTerm);
        LocalizationManager.Sources = new List<LanguageSourceData> { partialSource };
        var partial = Make(new I2LocalizationAdapter(_ => { }), new(), new());
        var polling = partial.ApplyInitially();
        Require(polling.MoveNext() && partialTerm.Writes == 1,
            "partial initialization must perform its first source application");
        partial.Dispose(); partial.Dispose();
        Require(!polling.MoveNext() && partialSource.UnsubscribeCount == 1,
            "retiring a partially initialized session must stop polling and unsubscribe");
        partialSource.RaiseUpdate(true);
        Require(partialTerm.Writes == 1, "partial session must ignore late update");
    }

    private static string Sha256(byte[] bytes) =>
        Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private static void Invoke(Plugin plugin, string method) =>
        typeof(Plugin).GetMethod(method, BindingFlags.Instance | BindingFlags.NonPublic)!
            .Invoke(plugin, null);

    private static void PackageAndPluginCases()
    {
        string directory = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)!;
        string overlayPath = Path.Combine(directory, "overlay.json");
        string manifestPath = Path.Combine(directory, "manifest.json");
        string gameRoot = Path.Combine(Path.GetTempPath(), "peglin-overlay-contract-" + Guid.NewGuid());
        string previousGameRoot = Paths.GameRootPath;
        byte[] assetBytes = Encoding.UTF8.GetBytes("contract game asset");
        byte[] assemblyBytes = Encoding.UTF8.GetBytes("contract game assembly");
        Require(!File.Exists(overlayPath) && !File.Exists(manifestPath),
            "test output must not contain a preexisting candidate package");
        string pluginHash = Sha256(File.ReadAllBytes(Assembly.GetExecutingAssembly().Location));
        string validOverlay = JsonSerializer.Serialize(new
        {
            schemaVersion = 1, kind = "peglin-korean-overlay", game = "Peglin", language = "ko",
            status = "draft", source = new
            {
                steamAppId = "1296610", steamBuildId = "test-build", unityVersion = "test-unity",
                assetSha256 = Sha256(assetBytes)
            },
            terms = new Dictionary<string, object> { ["term"] = new { translation = "translated" } }
        });
        string ManifestForBytes(byte[] overlayBytes) => JsonSerializer.Serialize(new
        {
            schemaVersion = 1, kind = "peglin-korean-client-candidate", game = "Peglin",
            steamAppId = "1296610", language = "ko", status = "draft", translationCount = 1,
            source = new
            {
                steamAppId = "1296610", steamBuildId = "test-build", unityVersion = "test-unity",
                assetSha256 = Sha256(assetBytes)
            },
            runtime = new { assemblyCSharpSha256 = Sha256(assemblyBytes) },
            files = new Dictionary<string, string>
            {
                ["BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll"] = pluginHash,
                ["BepInEx/plugins/PeglinKoreanRevised/overlay.json"] =
                    Sha256(overlayBytes)
            }
        });
        string ValidManifest(string overlay) => ManifestForBytes(Encoding.UTF8.GetBytes(overlay));
        byte[] EncodedWithPreamble(Encoding encoding, string content)
        {
            byte[] preamble = encoding.GetPreamble();
            byte[] body = encoding.GetBytes(content);
            byte[] result = new byte[preamble.Length + body.Length];
            Buffer.BlockCopy(preamble, 0, result, 0, preamble.Length);
            Buffer.BlockCopy(body, 0, result, preamble.Length, body.Length);
            return result;
        }
        void Write(string overlay, string manifest)
        {
            File.WriteAllText(overlayPath, overlay, new UTF8Encoding(false));
            File.WriteAllText(manifestPath, manifest, new UTF8Encoding(false));
        }

        try
        {
            string dataDirectory = Path.Combine(gameRoot, "Peglin_Data");
            Directory.CreateDirectory(Path.Combine(dataDirectory, "Managed"));
            File.WriteAllBytes(Path.Combine(dataDirectory, "resources.assets"), assetBytes);
            File.WriteAllBytes(Path.Combine(dataDirectory, "Managed", "Assembly-CSharp.dll"), assemblyBytes);
            Paths.GameRootPath = gameRoot;
            string validManifest = ValidManifest(validOverlay);
            Write(validOverlay, validManifest);
            var warnings = new List<string>();
            OverlayPackage package = OverlayPackage.Load(warnings.Add);
            Require(package.Translations.Count == 1 && package.Translations["term"] == "translated" &&
                package.SteamBuildId == "test-build" && warnings.Count == 1,
                "valid package metadata and draft warning");

            foreach (Encoding encoding in new Encoding[]
            {
                new UTF8Encoding(true), new UnicodeEncoding(false, true),
                new UnicodeEncoding(true, true)
            })
            {
                byte[] encodedOverlay = EncodedWithPreamble(encoding,
                    validOverlay.Replace("translated", "한글 번역"));
                File.WriteAllBytes(overlayPath, encodedOverlay);
                File.WriteAllText(manifestPath, ManifestForBytes(encodedOverlay), new UTF8Encoding(false));
                Require(OverlayPackage.Load(_ => { }).Translations["term"] == "한글 번역",
                    "valid BOM-encoded Korean overlay must retain its decoded translation");
            }

            string overlayA = validOverlay.Replace("translated", "번역 A");
            string overlayB = validOverlay.Replace("translated", "번역 B");
            Write(overlayA, ValidManifest(overlayA));
            Require(OverlayPackage.Load(_ => { }).Translations["term"] == "번역 A",
                "valid Korean overlay A must load with its own manifest");
            Write(overlayB, ValidManifest(overlayB));
            Require(OverlayPackage.Load(_ => { }).Translations["term"] == "번역 B",
                "valid Korean overlay B must load with its own manifest");

            Write(overlayA, ValidManifest(overlayB));
            bool replacedDuringLoad = false;
            try
            {
                OverlayPackage.Load(_ =>
                {
                    File.WriteAllText(overlayPath, overlayB, new UTF8Encoding(false));
                    replacedDuringLoad = true;
                });
                throw new Exception("overlay A was accepted under B's digest after replacement");
            }
            catch (InvalidDataException) { }
            Require(replacedDuringLoad &&
                File.ReadAllText(overlayPath, Encoding.UTF8) == overlayB,
                "replacement must occur during the actual draft warning boundary");

            Write(overlayA, ValidManifest(overlayA));
            OverlayPackage verifiedSnapshot = OverlayPackage.Load(_ =>
                File.WriteAllText(overlayPath, overlayB, new UTF8Encoding(false)));
            Require(verifiedSnapshot.Translations["term"] == "번역 A" &&
                File.ReadAllText(overlayPath, Encoding.UTF8) == overlayB,
                "a verified A snapshot may be consumed after its path changes to B");

            string[] invalidOverlays =
            {
                validOverlay.Replace("translated", ""),
                validOverlay.Replace("\"ko\"", "\"fr\""),
                validOverlay.Replace("\"test-build\"", "\"\"")
            };
            foreach (string invalid in invalidOverlays)
            {
                Write(invalid, validManifest);
                AssertInvalidPackageWithoutWrites(overlayPath, manifestPath);
            }
            Write(validOverlay, validManifest.Replace(pluginHash, new string('0', 64)));
            AssertInvalidPackageWithoutWrites(overlayPath, manifestPath);
            Write(validOverlay, validManifest.Replace("\"translationCount\":1", "\"translationCount\":2"));
            AssertInvalidPackageWithoutWrites(overlayPath, manifestPath);

            Write(validOverlay, validManifest);
            File.Delete(overlayPath);
            try { OverlayPackage.Load(_ => { }); throw new Exception("missing overlay was accepted"); }
            catch (FileNotFoundException) { }
            Directory.CreateDirectory(overlayPath);
            try { OverlayPackage.Load(_ => { }); throw new Exception("unreadable overlay was accepted"); }
            catch (UnauthorizedAccessException) { }
            finally { Directory.Delete(overlayPath); }
            Write(validOverlay, validManifest);
            File.Delete(manifestPath);
            try { OverlayPackage.Load(_ => { }); throw new Exception("missing manifest was accepted"); }
            catch (FileNotFoundException) { }

            SceneManager.Reset();
            Write(invalidOverlays[0], validManifest);
            var invalidPlugin = new Plugin();
            Invoke(invalidPlugin, "Awake");
            Invoke(invalidPlugin, "Start");
            Invoke(invalidPlugin, "OnDestroy");
            Invoke(invalidPlugin, "OnDestroy");
            Require(invalidPlugin.Logger.Error.Count == 1 &&
                SceneManager.SubscribeCount == 0 && invalidPlugin.StartedCoroutines.Count == 0,
                "invalid package must not start plugin work");

            SceneManager.Reset();
            LocalizationManager.Reset();
            var failedSource = new LanguageSourceData();
            var failedTerm = new TermData();
            failedSource.Terms.Add("term", failedTerm);
            LocalizationManager.Sources = new List<LanguageSourceData> { failedSource };
            Write(validOverlay, validManifest);
            var partialPlugin = new Plugin();
            partialPlugin.Logger.ThrowOnNextInfo = true;
            Invoke(partialPlugin, "Awake");
            Invoke(partialPlugin, "Start");
            Require(!partialPlugin.Logger.Info.Contains("Starting Peglin source file verification."),
                "failed Awake must not enter synchronous source verification in Start");
            Require(partialPlugin.StartedCoroutines.Count == 0 && LocalizationManager.InitializeCount == 0,
                "failed Awake must not schedule or perform translation work");
            SceneManager.Raise();
            Invoke(partialPlugin, "OnDestroy");
            Invoke(partialPlugin, "OnDestroy");
            SceneManager.Raise();
            failedSource.RaiseUpdate(true);
            Require(partialPlugin.Logger.Error.Count == 1 &&
                SceneManager.SubscribeCount == 0 &&
                partialPlugin.StartedCoroutines.Count == 0 &&
                failedSource.SubscribeCount == 0 && failedTerm.Writes == 0 &&
                LocalizationManager.InitializeCount == 0 && LocalizationManager.LocalizeCount == 0,
                "partially initialized plugin must retire once without scene work");

            SceneManager.Reset();
            LocalizationManager.Reset();
            var initialSource = new LanguageSourceData();
            var initialTerm = new TermData();
            initialSource.Terms.Add("term", initialTerm);
            LocalizationManager.Sources = new List<LanguageSourceData> { initialSource };
            var readyPlugin = new Plugin();
            Invoke(readyPlugin, "Awake");
            Require(SceneManager.SubscribeCount == 1 && readyPlugin.StartedCoroutines.Count == 0,
                "successful Awake must subscribe without scheduling work before verification");
            Invoke(readyPlugin, "Start");
            Require(readyPlugin.Logger.Info.Contains("Starting Peglin source file verification.") &&
                readyPlugin.Logger.Info.Exists(message => message.StartsWith("Verified resources.assets SHA-256 ", StringComparison.Ordinal)) &&
                readyPlugin.StartedCoroutines.Count == 1 && LocalizationManager.InitializeCount == 0,
                "successful Start must verify synchronously before scheduling initial application");
            Require(Drain(readyPlugin.StartedCoroutines[0]) == 29 && initialTerm.Writes == 1 &&
                initialTerm.Translation == "translated" && LocalizationManager.LocalizeCount == 1,
                "successful startup must apply translations with the stable-frame bound");
            var sceneSource = new LanguageSourceData();
            var sceneTerm = new TermData();
            sceneSource.Terms.Add("term", sceneTerm);
            LocalizationManager.Sources.Add(sceneSource);
            SceneManager.Raise();
            Require(readyPlugin.StartedCoroutines.Count == 2 &&
                Drain(readyPlugin.StartedCoroutines[1]) == 30 &&
                initialTerm.Writes == 1 && sceneTerm.Writes == 1 &&
                LocalizationManager.LocalizeCount == 2,
                "scene continuation must apply only the new I2 source");
            Invoke(readyPlugin, "OnDestroy");
            Invoke(readyPlugin, "OnDestroy");
            SceneManager.Raise();
            initialSource.RaiseUpdate(true);
            sceneSource.RaiseUpdate(true);
            Require(SceneManager.SubscribeCount == 1 && SceneManager.UnsubscribeCount == 1 &&
                initialSource.UnsubscribeCount == 1 && sceneSource.UnsubscribeCount == 1 &&
                readyPlugin.StartedCoroutines.Count == 2 &&
                initialTerm.Writes == 1 && sceneTerm.Writes == 1,
                "fully initialized plugin must retire scene and I2 callbacks once");
        }
        finally
        {
            Paths.GameRootPath = previousGameRoot;
            File.Delete(overlayPath);
            File.Delete(manifestPath);
            Directory.Delete(gameRoot, true);
        }
    }

    private static void AssertInvalidPackageWithoutWrites(string overlayPath, string manifestPath)
    {
        byte[] overlay = File.ReadAllBytes(overlayPath);
        byte[] manifest = File.ReadAllBytes(manifestPath);
        LocalizationManager.Reset();
        var source = new LanguageSourceData();
        var term = new TermData();
        source.Terms.Add("term", term);
        LocalizationManager.Sources = new List<LanguageSourceData> { source };
        try { OverlayPackage.Load(_ => { }); throw new Exception("invalid package was accepted"); }
        catch (InvalidDataException) { }
        Require(term.Writes == 0 && source.SubscribeCount == 0 &&
            LocalizationManager.LocalizeCount == 0 &&
            File.ReadAllBytes(overlayPath).AsSpan().SequenceEqual(overlay) &&
            File.ReadAllBytes(manifestPath).AsSpan().SequenceEqual(manifest),
            "invalid package must not write files or localization state");
    }

    public static int Main(string[] args)
    {
        if (args.Length > 0 && Array.Exists(args, value =>
            value != "session" && value != "adapter" && value != "package"))
        {
            throw new ArgumentException("Unknown OverlaySession contract case selector.");
        }
        if (args.Length == 0 || Array.IndexOf(args, "session") >= 0) SessionCases();
        if (args.Length == 0 || Array.IndexOf(args, "adapter") >= 0) AdapterCases();
        if (args.Length == 0 || Array.IndexOf(args, "package") >= 0) PackageAndPluginCases();
        Console.WriteLine("OverlaySession contract cases passed");
        return 0;
    }
}
