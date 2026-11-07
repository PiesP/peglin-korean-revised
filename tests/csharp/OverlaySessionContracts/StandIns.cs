#nullable enable
using System;
using System.Collections;
using System.Collections.Generic;
using System.Text.Json;

// Behavioral stand-ins for the game APIs. The production adapter, package parser,
// session, and plugin entry point are compiled from their actual source files.
namespace I2.Loc
{
    public sealed class TermData
    {
        public int Writes { get; private set; }
        public string? Translation { get; private set; }
        public void SetTranslation(int languageIndex, string value)
        {
            if (languageIndex != 0) throw new Exception("unexpected language index");
            Writes++;
            Translation = value;
        }
    }

    public sealed class LanguageSourceData
    {
        private Action<LanguageSourceData, bool, string>? updated;
        public readonly Dictionary<string, TermData> Terms = new();
        public bool HasKorean = true;
        public int SubscribeCount { get; private set; }
        public int UnsubscribeCount { get; private set; }

        public event Action<LanguageSourceData, bool, string> Event_OnSourceUpdateFromGoogle
        {
            add { updated += value; SubscribeCount++; }
            remove { updated -= value; UnsubscribeCount++; }
        }

        public int GetLanguageIndexFromCode(string code, bool exact, bool allowRegional)
        {
            if (code != "ko" || !exact || allowRegional) throw new Exception("language lookup changed");
            return HasKorean ? 0 : -1;
        }

        public TermData? GetTermData(string key, bool allowCategory)
        {
            if (allowCategory) throw new Exception("term lookup changed");
            return Terms.GetValueOrDefault(key);
        }

        public void RaiseUpdate(bool receivedNewData) => updated?.Invoke(this, receivedNewData, "");
    }

    public static class LocalizationManager
    {
        public static List<LanguageSourceData>? Sources { get; set; }
        public static int InitializeCount { get; private set; }
        public static int LocalizeCount { get; private set; }
        public static Action<int>? OnInitialize { get; set; }
        public static void InitializeIfNeeded()
        {
            InitializeCount++;
            OnInitialize?.Invoke(InitializeCount);
        }
        public static void LocalizeAll(bool force)
        {
            if (!force) throw new Exception("relocalization must be forced");
            LocalizeCount++;
        }
        public static void Reset()
        {
            Sources = null;
            InitializeCount = 0;
            LocalizeCount = 0;
            OnInitialize = null;
        }
    }
}

namespace Newtonsoft.Json.Linq
{
    public abstract class JToken
    {
        public virtual JToken? this[string key] => null;
        public static explicit operator string?(JToken? token) => (token as JValue)?.Text;
        public static explicit operator int?(JToken? token) =>
            int.TryParse((token as JValue)?.Text, out int number) ? number : null;

        internal static JToken From(JsonElement element) => element.ValueKind switch
        {
            JsonValueKind.Object => new JObject(element),
            JsonValueKind.String => new JValue(element.GetString()),
            JsonValueKind.Number => new JValue(element.GetRawText()),
            JsonValueKind.Null => new JValue(null),
            _ => throw new FormatException("unsupported test JSON value")
        };
    }

    internal sealed class JValue : JToken
    {
        internal string? Text { get; }
        internal JValue(string? text) { Text = text; }
    }

    public sealed class JProperty
    {
        public string Name { get; }
        public JToken Value { get; }
        internal JProperty(string name, JToken value) { Name = name; Value = value; }
    }

    public sealed class JObject : JToken
    {
        private readonly Dictionary<string, JToken> values = new(StringComparer.Ordinal);
        internal JObject(JsonElement element)
        {
            foreach (JsonProperty property in element.EnumerateObject())
                values.Add(property.Name, From(property.Value));
        }
        public static JObject Parse(string json)
        {
            using JsonDocument document = JsonDocument.Parse(json);
            return document.RootElement.ValueKind == JsonValueKind.Object
                ? new JObject(document.RootElement)
                : throw new FormatException("expected JSON object");
        }
        public override JToken? this[string key] => values.GetValueOrDefault(key);
        public int Count => values.Count;
        public IEnumerable<JProperty> Properties()
        {
            foreach (KeyValuePair<string, JToken> pair in values)
                yield return new JProperty(pair.Key, pair.Value);
        }
    }
}

namespace BepInEx
{
    [AttributeUsage(AttributeTargets.Class)]
    public sealed class BepInPluginAttribute : Attribute
    {
        public BepInPluginAttribute(string guid, string name, string version) { }
    }

    public static class Paths { public static string GameRootPath = ""; }

    public sealed class ManualLogSource
    {
        public readonly List<string> Info = new();
        public readonly List<string> Error = new();
        public readonly List<string> Warning = new();
        public bool ThrowOnNextInfo;
        public void LogInfo(object message)
        {
            if (ThrowOnNextInfo) { ThrowOnNextInfo = false; throw new Exception("injected partial initialization"); }
            Info.Add(message.ToString() ?? "");
        }
        public void LogError(object message) => Error.Add(message.ToString() ?? "");
        public void LogWarning(object message) => Warning.Add(message.ToString() ?? "");
    }

    public class BaseUnityPlugin
    {
        public ManualLogSource Logger { get; } = new();
        public readonly List<IEnumerator> StartedCoroutines = new();
        protected void StartCoroutine(IEnumerator routine) => StartedCoroutines.Add(routine);
    }
}

namespace UnityEngine.SceneManagement
{
    public readonly struct Scene { }
    public enum LoadSceneMode { Single }
    public static class SceneManager
    {
        private static Action<Scene, LoadSceneMode>? loaded;
        public static int SubscribeCount { get; private set; }
        public static int UnsubscribeCount { get; private set; }
        public static event Action<Scene, LoadSceneMode> sceneLoaded
        {
            add { loaded += value; SubscribeCount++; }
            remove { loaded -= value; UnsubscribeCount++; }
        }
        public static void Reset()
        {
            loaded = null;
            SubscribeCount = 0;
            UnsubscribeCount = 0;
        }
        public static void Raise() => loaded?.Invoke(new Scene(), LoadSceneMode.Single);
    }
}
