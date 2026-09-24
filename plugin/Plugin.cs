using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using BepInEx;
using I2.Loc;
using Newtonsoft.Json.Linq;
using UnityEngine.SceneManagement;

namespace PeglinKoreanRevised
{
    [BepInPlugin(PluginGuid, "Peglin Korean Revised", "0.1.2")]
    public sealed class Plugin : BaseUnityPlugin
    {
        private const string PluginGuid = "piesp.peglin.koreanrevised";
        private const int OverlaySchemaVersion = 1;
        private const string PluginPathInPackage =
            "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll";
        private const string OverlayPathInPackage =
            "BepInEx/plugins/PeglinKoreanRevised/overlay.json";

        private readonly Dictionary<string, string> translations =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private readonly HashSet<LanguageSourceData> subscribedSources =
            new HashSet<LanguageSourceData>();

        private readonly HashSet<LanguageSourceData> appliedSources =
            new HashSet<LanguageSourceData>();

        private string expectedAssetSha256;
        private string expectedAssemblySha256;
        private string expectedSteamBuildId;
        private int appliedTerms;
        private bool overlayLoaded;
        private bool sourceVerified;

        private void Awake()
        {
            try
            {
                LoadOverlay();
                Logger.LogInfo(
                    "Loaded " + translations.Count + " Korean terms for Steam build " +
                    expectedSteamBuildId + " and source asset " + expectedAssetSha256 + ".");
                Assembly assembly = Assembly.GetExecutingAssembly();
                Logger.LogInfo(
                    "Plugin assembly: " + assembly.Location +
                    " (assembly version " + assembly.GetName().Version + ").");
                SceneManager.sceneLoaded += OnSceneLoaded;
                overlayLoaded = true;
            }
            catch (Exception exception)
            {
                Logger.LogError("Korean overlay could not start: " + exception);
            }
        }

        private void Start()
        {
            if (!overlayLoaded)
            {
                return;
            }

            try
            {
                sourceVerified = VerifySourceFiles();
                if (sourceVerified)
                {
                    Logger.LogInfo("Waiting for the Korean I2 Localization source to become available.");
                    StartCoroutine(ApplyTranslationsWhenAvailable());
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("Korean source verification could not start: " + exception);
            }
        }

        private void LoadOverlay()
        {
            string pluginPath = Assembly.GetExecutingAssembly().Location;
            string pluginDirectory = Path.GetDirectoryName(pluginPath);
            string overlayPath = Path.Combine(pluginDirectory, "overlay.json");
            string manifestPath = Path.Combine(pluginDirectory, "manifest.json");
            JObject root = JObject.Parse(File.ReadAllText(overlayPath, Encoding.UTF8));
            JObject manifest = JObject.Parse(File.ReadAllText(manifestPath, Encoding.UTF8));

            if ((int?)root["schemaVersion"] != OverlaySchemaVersion ||
                (string)root["kind"] != "peglin-korean-overlay" ||
                (string)root["game"] != "Peglin" ||
                (string)root["language"] != "ko")
            {
                throw new InvalidDataException("Overlay metadata does not describe a supported Peglin Korean overlay.");
            }

            JObject source = root["source"] as JObject;
            if (source == null ||
                (string)source["steamAppId"] != "1296610" ||
                string.IsNullOrWhiteSpace((string)source["steamBuildId"]) ||
                string.IsNullOrWhiteSpace((string)source["unityVersion"]))
            {
                throw new InvalidDataException("Overlay Peglin source metadata is missing or invalid.");
            }

            expectedSteamBuildId = (string)source["steamBuildId"];
            expectedAssetSha256 = (string)source["assetSha256"];
            if (expectedAssetSha256 == null ||
                expectedAssetSha256.Length != 64 ||
                expectedAssetSha256.Any(character => !Uri.IsHexDigit(character)))
            {
                throw new InvalidDataException("Overlay source asset hash is missing or invalid.");
            }

            JObject terms = root["terms"] as JObject;
            if (terms == null || terms.Count == 0)
            {
                throw new InvalidDataException("Overlay contains no translation terms.");
            }

            foreach (JProperty property in terms.Properties())
            {
                string translation = (string)property.Value["translation"];
                if (string.IsNullOrWhiteSpace(property.Name) || string.IsNullOrWhiteSpace(translation))
                {
                    throw new InvalidDataException("Overlay contains an empty term key or translation.");
                }

                translations.Add(property.Name, translation);
            }

            string status = (string)root["status"];
            if (status == "draft")
            {
                Logger.LogWarning("This translation candidate is marked draft and has not been approved.");
            }
            else if (status != "approved")
            {
                throw new InvalidDataException("Overlay status must be draft or approved.");
            }

            JObject runtime = manifest["runtime"] as JObject;
            JObject manifestSource = manifest["source"] as JObject;
            JObject fileHashes = manifest["files"] as JObject;
            if ((int?)manifest["schemaVersion"] != 1 ||
                (string)manifest["kind"] != "peglin-korean-client-candidate" ||
                (string)manifest["game"] != "Peglin" ||
                (string)manifest["steamAppId"] != "1296610" ||
                (string)manifest["language"] != "ko" ||
                (string)manifest["status"] != status ||
                (int?)manifest["translationCount"] != terms.Count ||
                manifestSource == null ||
                (string)manifestSource["steamAppId"] != (string)source["steamAppId"] ||
                (string)manifestSource["steamBuildId"] != expectedSteamBuildId ||
                (string)manifestSource["unityVersion"] != (string)source["unityVersion"] ||
                (string)manifestSource["assetSha256"] != expectedAssetSha256 ||
                runtime == null || fileHashes == null)
            {
                throw new InvalidDataException("Candidate manifest does not match the translation overlay.");
            }

            expectedAssemblySha256 = (string)runtime["assemblyCSharpSha256"];
            string expectedPluginSha256 = (string)fileHashes[PluginPathInPackage];
            string expectedOverlaySha256 = (string)fileHashes[OverlayPathInPackage];
            if (!IsSha256(expectedAssemblySha256) ||
                !IsSha256(expectedPluginSha256) ||
                !IsSha256(expectedOverlaySha256))
            {
                throw new InvalidDataException("Candidate manifest contains a missing or invalid SHA-256 digest.");
            }

            if (!string.Equals(ComputeSha256(pluginPath), expectedPluginSha256, StringComparison.OrdinalIgnoreCase) ||
                !string.Equals(ComputeSha256(overlayPath), expectedOverlaySha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Plugin or overlay file hash does not match the candidate manifest.");
            }
        }

        private bool VerifySourceFiles()
        {
            Logger.LogInfo("Starting Peglin source file verification.");
            string gameRoot = Paths.GameRootPath;
            Logger.LogInfo("Using Peglin game root " + gameRoot + " for source verification.");
            string assetPath = Path.Combine(
                gameRoot,
                "Peglin_Data",
                "resources.assets");
            string assemblyPath = Path.Combine(
                gameRoot,
                "Peglin_Data",
                "Managed",
                "Assembly-CSharp.dll");
            if (!File.Exists(assetPath))
            {
                Logger.LogError("Peglin resources.assets was not found; no translations were applied.");
                return false;
            }
            if (!File.Exists(assemblyPath))
            {
                Logger.LogError("Peglin Assembly-CSharp.dll was not found; no translations were applied.");
                return false;
            }

            string assetHash;
            string assemblyHash;
            Stopwatch stopwatch = Stopwatch.StartNew();
            try
            {
                Logger.LogInfo(
                    "Hashing resources.assets (" + new FileInfo(assetPath).Length + " bytes) and " +
                    "Assembly-CSharp.dll (" + new FileInfo(assemblyPath).Length + " bytes) synchronously.");
                assetHash = ComputeSha256(assetPath);
                assemblyHash = ComputeSha256(assemblyPath);
            }
            catch (Exception exception)
            {
                Logger.LogError("Could not verify the Peglin source files: " + exception);
                return false;
            }

            if (!string.Equals(assetHash, expectedAssetSha256, StringComparison.OrdinalIgnoreCase))
            {
                Logger.LogError(
                    "The installed Peglin source asset does not match this candidate. " +
                    "Expected " + expectedAssetSha256 + ", found " + assetHash +
                    ". No translations were applied.");
                return false;
            }

            if (!string.Equals(assemblyHash, expectedAssemblySha256, StringComparison.OrdinalIgnoreCase))
            {
                Logger.LogError(
                    "The installed Peglin Assembly-CSharp.dll does not match this candidate. " +
                    "Expected " + expectedAssemblySha256 + ", found " + assemblyHash +
                    ". No translations were applied.");
                return false;
            }

            Logger.LogInfo(
                "Verified resources.assets SHA-256 " + assetHash +
                " and Assembly-CSharp.dll SHA-256 " + assemblyHash +
                " in " + stopwatch.ElapsedMilliseconds + " ms.");
            return true;
        }

        private System.Collections.IEnumerator ApplyTranslationsWhenAvailable()
        {
            int totalApplied = 0;
            int stableFrames = 0;
            for (int frame = 0; frame < 300 && stableFrames < 30; frame++)
            {
                LocalizationManager.InitializeIfNeeded();
                int newlyApplied = ApplyUnseenSources();
                if (newlyApplied > 0)
                {
                    totalApplied += newlyApplied;
                    LocalizationManager.LocalizeAll(true);
                }

                stableFrames = appliedSources.Count > 0 ? stableFrames + 1 : 0;
                if (stableFrames < 30)
                {
                    yield return null;
                }
            }

            if (totalApplied == 0)
            {
                Logger.LogError("No overlay terms matched the Korean I2 source; no translations were applied.");
                yield break;
            }

            appliedTerms = totalApplied;
            Logger.LogInfo(
                "Applied " + appliedTerms + " Korean translations to the in-memory I2 table.");
        }

        private int ApplyUnseenSources()
        {
            if (LocalizationManager.Sources == null)
            {
                return 0;
            }

            int totalApplied = 0;
            foreach (LanguageSourceData source in LocalizationManager.Sources.ToArray())
            {
                if (source == null || appliedSources.Contains(source))
                {
                    continue;
                }

                int count = ApplyToSource(source, false);
                if (count > 0)
                {
                    appliedSources.Add(source);
                    totalApplied += count;
                }
            }

            return totalApplied;
        }

        private int ApplyToSource(LanguageSourceData source, bool logMissing = true)
        {
            if (source == null)
            {
                return 0;
            }

            int koreanIndex = source.GetLanguageIndexFromCode("ko", true, false);
            if (koreanIndex < 0)
            {
                return 0;
            }

            if (subscribedSources.Add(source))
            {
                source.Event_OnSourceUpdateFromGoogle += OnSourceUpdated;
            }

            int applied = 0;
            int missing = 0;
            foreach (KeyValuePair<string, string> entry in translations)
            {
                TermData term = source.GetTermData(entry.Key, false);
                if (term == null)
                {
                    missing++;
                    continue;
                }

                term.SetTranslation(koreanIndex, entry.Value);
                applied++;
            }

            if (logMissing && missing > 0)
            {
                Logger.LogWarning(
                    "The I2 source is missing " + missing + " overlay terms; " +
                    applied + " matching terms were applied.");
            }

            return applied;
        }

        private void OnSourceUpdated(LanguageSourceData source, bool receivedNewData, string errorMessage)
        {
            if (!receivedNewData)
            {
                return;
            }

            int count = ApplyToSource(source);
            if (count > 0)
            {
                appliedSources.Add(source);
                LocalizationManager.LocalizeAll(true);
                Logger.LogInfo("Reapplied " + count + " Korean translations after an I2 source update.");
            }
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            if (sourceVerified)
            {
                StartCoroutine(ApplyNewSourcesAfterSceneLoad());
            }
        }

        private System.Collections.IEnumerator ApplyNewSourcesAfterSceneLoad()
        {
            for (int frame = 0; frame < 30; frame++)
            {
                LocalizationManager.InitializeIfNeeded();
                int count = ApplyUnseenSources();
                if (count > 0)
                {
                    LocalizationManager.LocalizeAll(true);
                    Logger.LogInfo("Applied " + count + " Korean translations to a newly loaded I2 source.");
                }

                yield return null;
            }
        }

        private void OnDestroy()
        {
            SceneManager.sceneLoaded -= OnSceneLoaded;
            foreach (LanguageSourceData source in subscribedSources)
            {
                if (source != null)
                {
                    source.Event_OnSourceUpdateFromGoogle -= OnSourceUpdated;
                }
            }
        }

        private static bool IsSha256(string value)
        {
            return value != null &&
                value.Length == 64 &&
                value.All(character => Uri.IsHexDigit(character));
        }

        private static string ComputeSha256(string path)
        {
            using (FileStream stream = File.OpenRead(path))
            using (SHA256 sha256 = SHA256.Create())
            {
                byte[] hash = sha256.ComputeHash(stream);
                StringBuilder result = new StringBuilder(hash.Length * 2);
                foreach (byte value in hash)
                {
                    result.Append(value.ToString("x2"));
                }

                return result.ToString();
            }
        }

    }
}
