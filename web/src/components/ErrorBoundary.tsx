import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import ErrorScreen from "./ErrorScreen";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

// Projedeki tek class component — React'te render hatalarını yakalamanın hook
// karşılığı yok, tek yol bu.
//
// react-router'ın errorElement'i bilerek kullanılmadı: o yalnızca data
// router'larda (createBrowserRouter + RouterProvider) çalışıyor, burada
// BrowserRouter + Routes var ve prop sessizce yok sayılırdı. Data router'a
// geçmenin tek kazancı loader/action hatalarını yakalamak olurdu; bu projede
// loader/action yok, bütün veri TanStack Query'den geliyor.
//
// Yakalanan hata kullanıcıya gösterilmiyor (React'in stack'i Türkçe değil ve
// operatöre bir şey anlatmıyor); geliştirici konsolda görüyor.
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error("ErrorBoundary yakaladı:", error, info.componentStack);
    }
  }

  // Fallback'ten çıkış: hasError sıfırlanınca children yeniden mount edilir
  // (fallback çizilirken unmount edilmişlerdi), yani ekran sıfırdan kurulur.
  // Hata kalıcıysa aynı fallback'e geri düşer, bu da doğru davranış.
  handleRetry = () => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <ErrorScreen
          title="Beklenmeyen bir hata oluştu"
          message="Ekran çizilirken bir sorun çıktı. Tekrar deneyebilir ya da sayfayı yenileyebilirsiniz."
          onRetry={this.handleRetry}
        />
      );
    }

    return this.props.children;
  }
}
