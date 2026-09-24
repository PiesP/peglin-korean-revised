using System.Collections.Generic;

namespace Newtonsoft.Json.Linq
{
    public class JToken
    {
        public JToken this[string propertyName]
        {
            get { return null; }
        }

        public static explicit operator int?(JToken value)
        {
            return null;
        }

        public static explicit operator string(JToken value)
        {
            return null;
        }
    }

    public class JObject : JToken
    {
        public int Count { get; }

        public static JObject Parse(string json)
        {
            return new JObject();
        }

        public IEnumerable<JProperty> Properties()
        {
            return new JProperty[0];
        }
    }

    public class JProperty
    {
        public string Name { get; }

        public JToken Value { get; }
    }
}
