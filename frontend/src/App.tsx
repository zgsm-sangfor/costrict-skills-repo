import { Routes, Route } from 'react-router'
import { I18nProvider } from './hooks/useI18n'
import { ThemeProvider } from './hooks/useTheme'
import Layout from './components/Layout'
import Home from './pages/Home'
import Browse from './pages/Browse'
import Detail from './pages/Detail'
import About from './pages/About'

export default function App() {
  return (
    <ThemeProvider>
      <I18nProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="browse" element={<Browse />} />
            <Route path="detail/:id" element={<Detail />} />
            <Route path="about" element={<About />} />
          </Route>
        </Routes>
      </I18nProvider>
    </ThemeProvider>
  )
}
