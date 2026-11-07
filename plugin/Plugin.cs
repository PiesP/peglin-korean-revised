using System;
using System.Reflection;
using BepInEx;
using UnityEngine.SceneManagement;

namespace PeglinKoreanRevised
{
    [BepInPlugin(PluginGuid, "Peglin Korean Revised", "0.1.2")]
    public sealed class Plugin : BaseUnityPlugin
    {
        private const string PluginGuid = "piesp.peglin.koreanrevised";
        private OverlayPackage package;
        private OverlaySession session;
        private bool sourceVerified;
        private bool sceneSubscribed;
        private bool disposed;

        private void Awake()
        {
            OverlaySession pendingSession = null;
            try
            {
                OverlayPackage loadedPackage = OverlayPackage.Load(message => Logger.LogWarning(message));
                pendingSession = new OverlaySession(loadedPackage.Translations,
                    new I2LocalizationAdapter(message => Logger.LogWarning(message)),
                    message => Logger.LogInfo(message), message => Logger.LogError(message));
                Logger.LogInfo("Loaded " + loadedPackage.Translations.Count +
                    " Korean terms for Steam build " + loadedPackage.SteamBuildId +
                    " and source asset " + loadedPackage.AssetSha256 + ".");
                Assembly assembly = Assembly.GetExecutingAssembly();
                Logger.LogInfo("Plugin assembly: " + assembly.Location +
                    " (assembly version " + assembly.GetName().Version + ").");
                sceneSubscribed = true;
                SceneManager.sceneLoaded += OnSceneLoaded;
                package = loadedPackage;
                session = pendingSession;
            }
            catch (Exception exception)
            {
                if (sceneSubscribed)
                {
                    sceneSubscribed = false;
                    SceneManager.sceneLoaded -= OnSceneLoaded;
                }
                pendingSession?.Dispose();
                Logger.LogError("Korean overlay could not start: " + exception);
            }
        }

        private void Start()
        {
            if (disposed || session == null) return;
            try
            {
                sourceVerified = SourceVerifier.Verify(Paths.GameRootPath, package,
                    message => Logger.LogInfo(message), message => Logger.LogError(message));
                if (sourceVerified)
                {
                    Logger.LogInfo("Waiting for the Korean I2 Localization source to become available.");
                    StartCoroutine(session.ApplyInitially());
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("Korean source verification could not start: " + exception);
            }
        }

        private void OnSceneLoaded(Scene scene, LoadSceneMode mode)
        {
            if (!disposed && sourceVerified && session != null)
                StartCoroutine(session.ApplyAfterSceneLoad());
        }

        private void OnDestroy()
        {
            if (disposed) return;
            disposed = true;
            if (sceneSubscribed)
            {
                sceneSubscribed = false;
                SceneManager.sceneLoaded -= OnSceneLoaded;
            }
            session?.Dispose();
        }
    }
}
