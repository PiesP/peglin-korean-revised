using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json.Linq;

namespace PeglinKoreanRevised
{
    internal sealed class OverlayPackage
    {
        private const int OverlaySchemaVersion = 1;
        private const string PluginPathInPackage = "BepInEx/plugins/PeglinKoreanRevised/PeglinKoreanRevised.dll";
        private const string OverlayPathInPackage = "BepInEx/plugins/PeglinKoreanRevised/overlay.json";

        internal IReadOnlyDictionary<string, string> Translations { get; }
        internal string AssetSha256 { get; }
        internal string AssemblySha256 { get; }
        internal string SteamBuildId { get; }

        private OverlayPackage(Dictionary<string, string> translations, string assetSha256,
            string assemblySha256, string steamBuildId)
        {
            Translations = translations;
            AssetSha256 = assetSha256;
            AssemblySha256 = assemblySha256;
            SteamBuildId = steamBuildId;
        }

        internal static OverlayPackage Load(Action<string> warn)
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

            string expectedSteamBuildId = (string)source["steamBuildId"];
            string expectedAssetSha256 = (string)source["assetSha256"];
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

            Dictionary<string, string> translations = new Dictionary<string, string>(StringComparer.Ordinal);
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
                warn("This translation candidate is marked draft and has not been approved.");
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

            string expectedAssemblySha256 = (string)runtime["assemblyCSharpSha256"];
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
            return new OverlayPackage(translations, expectedAssetSha256, expectedAssemblySha256, expectedSteamBuildId);
        }

        internal static bool IsSha256(string value)
        {
            return value != null &&
                value.Length == 64 &&
                value.All(character => Uri.IsHexDigit(character));
        }

        internal static string ComputeSha256(string path)
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
