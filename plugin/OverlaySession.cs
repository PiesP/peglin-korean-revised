using System;
using System.Collections;
using System.Collections.Generic;

namespace PeglinKoreanRevised
{
    internal interface ILocalizationPort
    {
        void Initialize();
        IEnumerable<object> Sources();
        int Apply(object source, IReadOnlyDictionary<string, string> terms,
            bool logMissing, Action<object, bool> callback);
        void Dispose();
        void LocalizeAll();
    }

    internal sealed class OverlaySession
    {
        private readonly IReadOnlyDictionary<string, string> translations;
        private readonly ILocalizationPort localization;
        private readonly Action<string> info;
        private readonly Action<string> error;
        private readonly HashSet<object> appliedSources = new HashSet<object>();
        private bool disposed;
        private int appliedTerms;

        internal OverlaySession(IReadOnlyDictionary<string, string> translations,
            ILocalizationPort localization, Action<string> info, Action<string> error)
        {
            this.translations = translations;
            this.localization = localization;
            this.info = info;
            this.error = error;
        }

        internal IEnumerator ApplyInitially()
        {
            int totalApplied = 0;
            int stableFrames = 0;
            for (int frame = 0; frame < 300 && stableFrames < 30 && !disposed; frame++)
            {
                localization.Initialize();
                int newlyApplied = ApplyUnseenSources();
                if (newlyApplied > 0)
                {
                    totalApplied += newlyApplied;
                    localization.LocalizeAll();
                }
                stableFrames = appliedSources.Count > 0 ? stableFrames + 1 : 0;
                if (stableFrames < 30) yield return null;
            }
            if (disposed) yield break;
            if (totalApplied == 0)
            {
                error("No overlay terms matched the Korean I2 source; no translations were applied.");
                yield break;
            }
            appliedTerms = totalApplied;
            info("Applied " + appliedTerms + " Korean translations to the in-memory I2 table.");
        }

        internal IEnumerator ApplyAfterSceneLoad()
        {
            for (int frame = 0; frame < 30 && !disposed; frame++)
            {
                localization.Initialize();
                int count = ApplyUnseenSources();
                if (count > 0)
                {
                    localization.LocalizeAll();
                    info("Applied " + count + " Korean translations to a newly loaded I2 source.");
                }
                yield return null;
            }
        }

        private int ApplyUnseenSources()
        {
            int totalApplied = 0;
            foreach (object source in localization.Sources())
            {
                if (source == null || appliedSources.Contains(source)) continue;
                int count = localization.Apply(source, translations, false, OnSourceUpdated);
                if (count > 0)
                {
                    appliedSources.Add(source);
                    totalApplied += count;
                }
            }
            return totalApplied;
        }

        private void OnSourceUpdated(object source, bool receivedNewData)
        {
            if (disposed || !receivedNewData) return;
            int count = localization.Apply(source, translations, true, OnSourceUpdated);
            if (count > 0)
            {
                appliedSources.Add(source);
                localization.LocalizeAll();
                info("Reapplied " + count + " Korean translations after an I2 source update.");
            }
        }

        internal void Dispose()
        {
            if (disposed) return;
            disposed = true;
            localization.Dispose();
            appliedSources.Clear();
        }
    }
}
