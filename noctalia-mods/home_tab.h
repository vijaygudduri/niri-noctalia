#pragma once

#include "core/timer_manager.h"
#include "render/core/render_styles.h"
#include "render/core/thumbnail_service.h"
#include "shell/control_center/control_center_services.h"
#include "shell/control_center/shortcut_services.h"
#include "shell/control_center/tab.h"
#include "ui/signal.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <vector>

class AccountsService;
class Button;
class Box;
class CompositorPlatform;
class IpcService;
class ConfigService;
class DependencyService;
class EffectNode;
class Glyph;
class GridView;
class Image;
class InputArea;
class Label;
class Shortcut;
class Slider;
class PipeWireService;
class BrightnessService;
class Wallpaper;
class ThumbnailService;
class AnimationManager;
class WeatherService;

namespace scripting {
  class ScriptApiContext;
}

struct ShortcutPad {
  std::unique_ptr<Shortcut> shortcut;
  Button* button = nullptr;
  Glyph* glyph = nullptr;
  Label* label = nullptr;

  // Cached last-applied style, so syncShortcuts() can skip redundant restyles
  // when nothing has actually changed since the previous sync.
  bool styleInitialized = false;
  bool styleEnabled = false;
  bool styleActive = false;
  float styleFillOpacity = -1.0f;
  std::string styleGlyph;

  // Cached last-applied label max width, so doLayout() can skip redundant
  // setMaxWidth() calls when the computed cell width hasn't actually changed.
  float styleMaxWidth = -1.0f;
};

class HomeTab : public Tab {
public:
  explicit HomeTab(const ControlCenterServices& services);
  ~HomeTab() override;

  std::unique_ptr<Flex> create() override;
  std::unique_ptr<Flex> createHeaderActions() override;
  void onFrameTick(float deltaMs) override;
  void setActive(bool active) override;
  void onClose() override;

private:
  void doLayout(Renderer& renderer, float contentWidth, float bodyHeight) override;
  void doUpdate(Renderer& renderer) override;
  void sync(Renderer& renderer);
  void syncScaledFonts();
  void syncShortcuts();
  void syncVolumeSlider();
  void syncBrightnessSlider();
  void hideWeatherEffect();
  void layoutWallpaperBackground(Renderer& renderer);
  void ensureWallpaperThumbnail(const std::string& path, int targetPx);
  void syncWallpaperBackground(Renderer& renderer);
  void startCrispFade();
  void cancelCrispFade();
  struct CardOverlayOptions {
    bool keyboardFocus = true;
    bool pointerHitTest = true;
  };
  InputArea* addCardOverlay(Flex& card, std::function<void()> onActivate);
  InputArea* addCardOverlay(Flex& card, std::function<void()> onActivate, CardOverlayOptions options);
  void layoutCardOverlays();
  void onPanelCardOpacityChanged(float opacity) override;
  void kickShortcutResync();

  // Services
  PipeWireService* m_audio = nullptr;
  BrightnessService* m_brightness = nullptr;
  ConfigService* m_config = nullptr;
  AccountsService* m_accounts = nullptr;
  Wallpaper* m_wallpaper = nullptr;
  ThumbnailService* m_thumbnails = nullptr;
  ShortcutServices m_services;
  WeatherService* m_weather = nullptr;
  bool m_active = false;

  // User card
  Flex* m_rootLayout = nullptr;
  Flex* m_userCard = nullptr;
  InputArea* m_userAvatarArea = nullptr;
  InputArea* m_userCardArea = nullptr;
  InputArea* m_userCardKeyboardArea = nullptr;
  Image* m_userAvatar = nullptr;
  Flex* m_userMain = nullptr;
  Label* m_userHost = nullptr;
  Label* m_userUptime = nullptr;
  Label* m_userVersion = nullptr;
  std::string m_loadedAvatarPath;
  int m_loadedAvatarSize = 0;

  // Wallpaper background layers
  Image* m_wallpaperPlaceholder = nullptr;
  Image* m_wallpaperBg = nullptr;
  Box* m_wallpaperGradient = nullptr;
  std::string m_loadedWallpaperPath;
  int m_loadedWallpaperSize = 0;
  std::string m_crispWorkingPath;
  int m_crispWorkingSize = 0;
  bool m_crispShown = false;
  bool m_crispNeedsFade = false;
  std::uint32_t m_wallpaperCrispAnimId = 0;
  ThumbnailService::Subscription m_thumbnailPendingSub;
  Signal<>::ScopedConnection m_wallpaperChangedConn;

  // Slider card
  Slider* m_volumeSlider = nullptr;
  Label* m_volumeLabel = nullptr;
  Glyph* m_volumeGlyph = nullptr;
  Slider* m_brightnessSlider = nullptr;
  Label* m_brightnessLabel = nullptr;
  Glyph* m_brightnessGlyph = nullptr;

  // Volume write state
  std::uint32_t m_pendingSinkId = 0;
  float m_pendingSinkVolume = -1.0f;
  bool m_syncingVolume = false;
  bool m_syncingBrightness = false;
  Timer m_volumeDebounceTimer;
  Timer m_shortcutSyncTimer;
  int m_shortcutSyncTicksRemaining = 0;

  // Brightness write state
  std::string m_primaryDisplayId;
  float m_lastBrightness = -1.0f;
  bool m_pendingBrightness = false;
  float m_pendingBrightnessValue = 0.0f;
  Timer m_brightnessDebounceTimer;

  // Shortcuts
  Button* m_settingsButton = nullptr;
  Button* m_sessionButton = nullptr;
  GridView* m_shortcutsGrid = nullptr;
  std::vector<ShortcutPad> m_shortcutPads;

  // Info Card elements (weather – matches WeatherTab's current-conditions card, minus location)
  Flex* m_infoCard = nullptr;
  Glyph* m_weatherGlyph = nullptr;
  Label* m_weatherTempLabel = nullptr;
  Label* m_weatherHiLoLabel = nullptr;
  Label* m_weatherDescLabel = nullptr;
  EffectNode* m_weatherEffectNode = nullptr;
  EffectType m_weatherActiveEffect = EffectType::None;
  float m_weatherShaderTime = 0.0f;
};
