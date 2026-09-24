using System.Collections;

namespace UnityEngine
{
    public class Object
    {
    }

    public class Component : Object
    {
    }

    public class Behaviour : Component
    {
    }

    public class MonoBehaviour : Behaviour
    {
        protected Coroutine StartCoroutine(IEnumerator routine)
        {
            return null;
        }
    }

    public sealed class Coroutine
    {
    }
}

namespace UnityEngine.Events
{
    public delegate void UnityAction<T0, T1>(T0 arg0, T1 arg1);
}

namespace UnityEngine.SceneManagement
{
    public struct Scene
    {
    }

    public enum LoadSceneMode
    {
        Single,
        Additive
    }

    public static class SceneManager
    {
        public static event UnityEngine.Events.UnityAction<Scene, LoadSceneMode> sceneLoaded
        {
            add { }
            remove { }
        }
    }
}
