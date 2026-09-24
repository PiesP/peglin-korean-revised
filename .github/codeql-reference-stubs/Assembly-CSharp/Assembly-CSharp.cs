using System;
using System.Collections.Generic;

namespace I2.Loc
{
    public delegate void SourceUpdateHandler(
        LanguageSourceData source,
        bool receivedNewData,
        string errorMessage);

    public class LanguageSourceData
    {
        public event SourceUpdateHandler Event_OnSourceUpdateFromGoogle
        {
            add { }
            remove { }
        }

        public int GetLanguageIndexFromCode(
            string languageCode,
            bool allowApproximation,
            bool skipDisabled)
        {
            return -1;
        }

        public TermData GetTermData(string term, bool allowCategoryMismatch)
        {
            return null;
        }
    }

    public class TermData
    {
        public void SetTranslation(int languageIndex, string translation)
        {
        }
    }

    public static class LocalizationManager
    {
        public static List<LanguageSourceData> Sources { get; } = new List<LanguageSourceData>();

        public static void InitializeIfNeeded()
        {
        }

        public static void LocalizeAll(bool force)
        {
        }
    }
}
