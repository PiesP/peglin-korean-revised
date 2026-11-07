using System;
using System.Diagnostics;
using System.IO;

namespace PeglinKoreanRevised
{
    internal static class SourceVerifier
    {
        internal static bool Verify(string gameRoot, OverlayPackage package, Action<string> info, Action<string> error)
        {
            info("Starting Peglin source file verification.");
            info("Using Peglin game root " + gameRoot + " for source verification.");
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
                error("Peglin resources.assets was not found; no translations were applied.");
                return false;
            }
            if (!File.Exists(assemblyPath))
            {
                error("Peglin Assembly-CSharp.dll was not found; no translations were applied.");
                return false;
            }

            string assetHash;
            string assemblyHash;
            Stopwatch stopwatch = Stopwatch.StartNew();
            try
            {
                info(
                    "Hashing resources.assets (" + new FileInfo(assetPath).Length + " bytes) and " +
                    "Assembly-CSharp.dll (" + new FileInfo(assemblyPath).Length + " bytes) synchronously.");
                assetHash = OverlayPackage.ComputeSha256(assetPath);
                assemblyHash = OverlayPackage.ComputeSha256(assemblyPath);
            }
            catch (Exception exception)
            {
                error("Could not verify the Peglin source files: " + exception);
                return false;
            }

            if (!string.Equals(assetHash, package.AssetSha256, StringComparison.OrdinalIgnoreCase))
            {
                error(
                    "The installed Peglin source asset does not match this candidate. " +
                    "Expected " + package.AssetSha256 + ", found " + assetHash +
                    ". No translations were applied.");
                return false;
            }

            if (!string.Equals(assemblyHash, package.AssemblySha256, StringComparison.OrdinalIgnoreCase))
            {
                error(
                    "The installed Peglin Assembly-CSharp.dll does not match this candidate. " +
                    "Expected " + package.AssemblySha256 + ", found " + assemblyHash +
                    ". No translations were applied.");
                return false;
            }

            info(
                "Verified resources.assets SHA-256 " + assetHash +
                " and Assembly-CSharp.dll SHA-256 " + assemblyHash +
                " in " + stopwatch.ElapsedMilliseconds + " ms.");
            return true;
        }

    }
}
