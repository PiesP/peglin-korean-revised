using System;
using System.Collections.Generic;
using System.Linq;
using I2.Loc;

namespace PeglinKoreanRevised
{
    internal sealed class I2LocalizationAdapter : ILocalizationPort
    {
        private readonly HashSet<LanguageSourceData> subscribed = new HashSet<LanguageSourceData>();
        private readonly Action<string> warn;
        private Action<object, bool> onUpdate;
        private bool disposed;

        internal I2LocalizationAdapter(Action<string> warn) { this.warn = warn; }

        public void Initialize() { LocalizationManager.InitializeIfNeeded(); }
        public IEnumerable<object> Sources()
        {
            return LocalizationManager.Sources == null
                ? Enumerable.Empty<object>()
                : LocalizationManager.Sources.ToArray().Cast<object>();
        }
        public int Apply(object handle, IReadOnlyDictionary<string, string> terms,
            bool logMissing, Action<object, bool> callback)
        {
            if (disposed || !(handle is LanguageSourceData source)) return 0;
            int koreanIndex = source.GetLanguageIndexFromCode("ko", true, false);
            if (koreanIndex < 0) return 0;
            onUpdate = callback;
            if (subscribed.Add(source)) source.Event_OnSourceUpdateFromGoogle += OnSourceUpdated;
            int applied = 0;
            int missing = 0;
            foreach (KeyValuePair<string, string> entry in terms)
            {
                TermData term = source.GetTermData(entry.Key, false);
                if (term == null) { missing++; continue; }
                term.SetTranslation(koreanIndex, entry.Value);
                applied++;
            }
            if (logMissing && missing > 0)
                warn("The I2 source is missing " + missing + " overlay terms; " +
                    applied + " matching terms were applied.");
            return applied;
        }
        private void OnSourceUpdated(LanguageSourceData source, bool receivedNewData, string errorMessage)
        {
            if (!disposed) onUpdate?.Invoke(source, receivedNewData);
        }
        public void LocalizeAll() { if (!disposed) LocalizationManager.LocalizeAll(true); }
        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            foreach (LanguageSourceData source in subscribed)
                if (source != null) source.Event_OnSourceUpdateFromGoogle -= OnSourceUpdated;
            subscribed.Clear();
            onUpdate = null;
        }
    }
}
