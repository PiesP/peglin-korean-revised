using System;
using System.Collections;
using System.Collections.Generic;
using PeglinKoreanRevised;

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

    public static int Main()
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
        Console.WriteLine("OverlaySession contract cases passed");
        return 0;
    }
}
