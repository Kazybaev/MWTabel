import { useEffect, useEffectEvent, useState } from "react";

export function useResource(loader, deps) {
  const [state, setState] = useState({
    data: null,
    error: "",
    loading: true,
    refreshing: false,
  });

  const load = useEffectEvent(async () => {
    setState((currentState) => ({
      ...currentState,
      loading: currentState.data == null,
      refreshing: currentState.data != null,
      error: "",
    }));

    try {
      const data = await loader();
      setState({
        data,
        error: "",
        loading: false,
        refreshing: false,
      });
    } catch (error) {
      setState((currentState) => ({
        ...currentState,
        error: error.message,
        loading: false,
        refreshing: false,
      }));
    }
  });

  useEffect(() => {
    load();
  }, deps);

  return {
    ...state,
    reload: load,
    setData: (updater) => {
      setState((currentState) => ({
        ...currentState,
        data: typeof updater === "function" ? updater(currentState.data) : updater,
      }));
    },
  };
}
